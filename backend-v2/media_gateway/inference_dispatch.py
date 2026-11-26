"""Dispatch bounded sampled frames to the authenticated inference v1 worker."""

import asyncio
import json
import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from uuid import UUID, uuid4

import httpx
from PIL import Image

from app.contracts.inference import FrameRef, InferenceRequest, InferenceResponse
from inference_worker.contract import INFERENCE_PATH
from media_gateway.frame_queue import FrameQueue, SampledFrame
from media_gateway.video_source import MAX_HEIGHT, MAX_WIDTH

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 512 * 1024
MAX_DETECTIONS = 300


def _unique_json_fields(pairs):
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError('Duplicate inference response field')
    return values


@dataclass(frozen=True, slots=True)
class CameraAssignment:
    """Trusted control-plane attribution and model selection for one camera."""

    organization_id: UUID
    site_id: UUID
    camera_id: UUID
    model_version_id: UUID
    model_key: str
    model_version: str
    class_map: Mapping[str, str]

    def __post_init__(self) -> None:
        if not all(isinstance(value, UUID) for value in (
            self.organization_id, self.site_id, self.camera_id, self.model_version_id,
        )):
            raise ValueError('Assignment requires UUID identifiers')
        if (not 1 <= len(self.model_key) <= 100 or not self.model_key.isprintable()
                or not 1 <= len(self.model_version) <= 64 or not self.model_version.isprintable()):
            raise ValueError('Invalid assigned model identity')
        labels = dict(self.class_map)
        if not labels or any(not isinstance(label, str) or not 1 <= len(label) <= 100
                             or kind not in ('person', 'helmet', 'vest')
                             for label, kind in labels.items()):
            raise ValueError('Invalid assigned class map')
        object.__setattr__(self, 'class_map', MappingProxyType(labels))


@dataclass(frozen=True, slots=True)
class FrameAttribution:
    camera_id: str
    received_at: datetime
    source_timestamp: float
    source_frame_index: int
    source_epoch: int
    sampled_monotonic: float
    sample_interval: float
    width: int
    height: int

    @classmethod
    def from_sample(cls, frame: SampledFrame):
        if (not isinstance(frame.received_at, datetime) or frame.received_at.utcoffset() is None
                or type(frame.width) is not int or not 1 <= frame.width <= MAX_WIDTH
                or type(frame.height) is not int or not 1 <= frame.height <= MAX_HEIGHT
                or type(frame.source_frame_index) is not int or frame.source_frame_index < 0
                or type(frame.source_epoch) is not int or frame.source_epoch < 1
                or any(type(value) not in (int, float) or not isfinite(value) for value in (
                    frame.source_timestamp, frame.sampled_monotonic, frame.sample_interval,
                )) or frame.sample_interval <= 0
                or type(frame.data) is not bytes or len(frame.data) != frame.width * frame.height * 3):
            raise DispatchError('invalid_frame')
        return cls(frame.camera_id, frame.received_at, frame.source_timestamp, frame.source_frame_index,
                   frame.source_epoch, frame.sampled_monotonic, frame.sample_interval, frame.width, frame.height)


@dataclass(frozen=True, slots=True)
class InferenceResult:
    assignment: CameraAssignment
    frame: FrameAttribution
    response: InferenceResponse


class DispatchError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class InferenceDispatcher:
    """One in-flight request. Drop failed frames and let the next sample proceed."""

    def __init__(self, queue: FrameQueue, assignments: Mapping[str, CameraAssignment], frame_root: Path,
                 *, worker_origin: str, token: str, timeout: float = 5,
                 transport: httpx.AsyncBaseTransport | None = None):
        origin = httpx.URL(worker_origin)
        if (origin.scheme != 'https' or not origin.host or origin.userinfo or origin.query
                or origin.fragment or origin.path not in ('', '/')):
            raise ValueError('Inference worker must use a configured HTTPS origin')
        if not 32 <= len(token) <= 256 or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError('Invalid inference credential')
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError('Invalid inference deadline')

        self._assignments = dict(assignments)
        if any(key != str(value.camera_id) for key, value in self._assignments.items()):
            raise ValueError('Assignment key must match its camera ID')
        self._frames = frame_root.resolve(strict=True) / 'frames'
        if self._frames.is_symlink() or not self._frames.is_dir():
            raise ValueError('Expected a protected frames directory')
        self._queue = queue
        self._timeout = timeout
        self._active = asyncio.Lock()
        self._storage_fault = False
        self._client = httpx.AsyncClient(
            base_url=origin, follow_redirects=False, trust_env=False, timeout=timeout, transport=transport,
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json',
                     'Accept-Encoding': 'identity', 'Cache-Control': 'no-store'},
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    @contextmanager
    def _stage(self, sample: SampledFrame, name: str) -> Iterator[None]:
        path = self._frames / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
        descriptor = os.open(path, flags, 0o640)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                with Image.frombytes('RGB', (sample.width, sample.height), sample.data) as image:
                    image.save(output, format='PNG', compress_level=1)
            yield
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                self._storage_fault = True
                raise

    async def dispatch_one(self) -> InferenceResult | None:
        if self._active.locked():
            raise DispatchError('busy')
        async with self._active:
            if self._storage_fault:
                raise DispatchError('frame_storage')
            sample = self._queue.take()
            if sample is None:
                return None

            request_id, frame_id = uuid4(), uuid4()
            try:
                assignment = self._assignments.get(sample.camera_id)
                if assignment is None:
                    raise DispatchError('unknown_camera')
                frame = FrameAttribution.from_sample(sample)
                name = f'{frame_id}.png'
                request = InferenceRequest(
                    request_id=request_id, frame_id=str(frame_id), model_key=assignment.model_key,
                    model_version=assignment.model_version, frame=FrameRef(
                        object_key=f'frames/{name}', width=frame.width, height=frame.height,
                        content_type='image/png',
                    ),
                )
                try:
                    with self._stage(sample, name):
                        async with asyncio.timeout(self._timeout):
                            result = await self._infer(request, assignment)
                except (TimeoutError, httpx.TimeoutException):
                    raise DispatchError('timeout') from None
                except httpx.HTTPError:
                    raise DispatchError('worker_failure') from None
                except OSError:
                    raise DispatchError('frame_storage') from None
            except DispatchError as error:
                logger.warning('inference_dispatch_failed', extra={
                    'correlation_id': str(request_id), 'reason': error.code,
                })
                raise

            logger.info('inference_dispatch_succeeded', extra={'correlation_id': str(request_id)})
            return InferenceResult(assignment, frame, result)

    async def _infer(self, request: InferenceRequest, assignment: CameraAssignment) -> InferenceResponse:
        async with self._client.stream('POST', INFERENCE_PATH, json=request.model_dump(mode='json')) as response:
            if response.status_code in (401, 403):
                raise DispatchError('unauthorized')
            if response.status_code == 503:
                raise DispatchError('unavailable')
            if response.status_code != 200:
                raise DispatchError('worker_failure')
            if (response.headers.get('content-encoding', 'identity').lower() != 'identity'
                    or response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                    != 'application/json'):
                raise DispatchError('invalid_response')
            payload = bytearray()
            async for chunk in response.aiter_bytes():
                if len(payload) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise DispatchError('invalid_response')
                payload.extend(chunk)

        try:
            raw = json.loads(payload, object_pairs_hook=_unique_json_fields)
            if not isinstance(raw, dict) or raw.get('schema_version') != request.schema_version:
                raise ValueError('Incompatible inference version')
            result = InferenceResponse.model_validate_json(payload, strict=True)
            if (result.request_id != request.request_id or result.frame_id != request.frame_id
                    or result.model_key != request.model_key or result.model_version != request.model_version
                    or not isfinite(result.inference_ms) or len(result.detections) > MAX_DETECTIONS):
                raise ValueError('Unmatched inference response')
            for item in result.detections:
                if (assignment.class_map.get(item.original_class) != item.class_key
                        or not all(isfinite(value) for value in (*item.bbox_xyxy, item.score))
                        or item.bbox_xyxy[2] > request.frame.width or item.bbox_xyxy[3] > request.frame.height):
                    raise ValueError('Invalid inference detection')
        except (ValueError, RecursionError):
            raise DispatchError('invalid_response') from None
        return result
