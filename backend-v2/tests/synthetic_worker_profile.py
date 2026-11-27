"""Observe synthetic worker timings without modifying the inference contract."""

import asyncio
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from math import isfinite
from time import perf_counter
from unittest.mock import patch

import httpx

from inference_worker import service
from inference_worker.contract import INFERENCE_PATH
from inference_worker.onnx_cpu import factory as cpu_factory

WORKER_PHASES = ('eligibility', 'model_load', 'adapter_infer')
_timings = ContextVar('synthetic_worker_timings', default=None)


@contextmanager
def measure(phase):
    started = perf_counter()
    try:
        yield
    finally:
        if (values := _timings.get()) is not None:
            values[phase] = values.get(phase, 0) + (perf_counter() - started) * 1000


class ProfiledAuthority(service.AuthorityClient):
    def get(self, request):
        with measure('eligibility'):
            return super().get(request)


class ProfiledRuntime:
    def __init__(self):
        self.runtime = cpu_factory()

    @contextmanager
    def load(self, artifact):
        with ExitStack() as stack:
            with measure('model_load'):
                model = stack.enter_context(self.runtime.load(artifact))
            yield model

    def infer(self, model, frame, request):
        with measure('adapter_infer'):
            return self.runtime.infer(model, frame, request)


def worker_factory():
    with patch.object(service, 'AuthorityClient', ProfiledAuthority):
        app = service.from_environment()

    async def instrumented_app(scope, receive, send):
        timings = {}
        context_token = _timings.set(timings)

        async def send_timings(message):
            if (message['type'] == 'http.response.start' and message['status'] == 200
                    and scope['path'] == INFERENCE_PATH):
                headers = [(f'x-ppe-test-{phase}-ms'.encode(), f'{timings[phase]:.6f}'.encode())
                           for phase in WORKER_PHASES]
                message = {**message, 'headers': [*message['headers'], *headers]}
            await send(message)

        try:
            await app(scope, receive, send_timings)
        finally:
            _timings.reset(context_token)

    return instrumented_app


class ProfiledTransport(httpx.AsyncHTTPTransport):
    """Measure one request at a time for the single-dispatcher capacity test."""

    def __init__(self, context):
        super().__init__(verify=context, trust_env=False)
        self.starts_at = None
        self.phases = None

    async def handle_async_request(self, request):
        self.starts_at = asyncio.get_running_loop().time()
        self.phases = None
        response = await super().handle_async_request(request)
        if response.status_code == 200:
            try:
                phases = {phase: float(response.headers[f'x-ppe-test-{phase}-ms'])
                          for phase in WORKER_PHASES}
                assert all(isfinite(value) and value >= 0 for value in phases.values())
            except (AssertionError, KeyError, ValueError):
                await response.aclose()
                raise AssertionError('Missing or invalid synthetic worker phase timings') from None
            self.phases = phases
        return response
