"""The isolated model loader receives an immutable, verified byte snapshot."""

import hmac
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import ContextManager, Protocol
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException

from app.contracts.inference import Detection, InferenceRequest, InferenceResponse
from app.model_artifact_integrity import check_artifact, read_small
from app.model_artifacts import within_namespace
from inference_worker.auth import InternalRoute, read_token, require_token
from inference_worker.contract import INFERENCE_PATH, LEASE_PATH, MAX_LEASE_SECONDS, LeaseRequest, ModelLease


class ModelRuntime(Protocol):
    def load(self, artifact: bytes) -> ContextManager[object]: ...

    def infer(self, model: object, frame: bytes, request: InferenceRequest) -> list[Detection]: ...


@dataclass(frozen=True)
class LiveLease:
    lease: ModelLease
    deadline: float

    def require_current(self):
        if time.monotonic() >= self.deadline or datetime.now(timezone.utc) >= self.lease.expires_at:
            raise ValueError('Eligibility lease expired')


class AuthorityClient:
    def __init__(self, client: httpx.Client, token: str):
        self.client = client
        self.token = token

    def get(self, request: InferenceRequest) -> LiveLease:
        query = LeaseRequest(model_key=request.model_key, model_version=request.model_version, nonce=uuid4())
        started = time.monotonic()
        response = self.client.post(LEASE_PATH, json=query.model_dump(mode='json'), headers={
            'Authorization': f'Bearer {self.token}', 'Cache-Control': 'no-store',
        })
        response.raise_for_status()
        lease = ModelLease.model_validate_json(response.content)
        if (lease.model_key, lease.model_version, lease.nonce) != (query.model_key, query.model_version, query.nonce):
            raise ValueError('Eligibility response binding invalid')
        lifetime = (lease.expires_at - lease.issued_at).total_seconds()
        if not 0 < lifetime <= MAX_LEASE_SECONDS:
            raise ValueError('Eligibility lease lifetime invalid')
        current = LiveLease(lease, started + lifetime)
        current.require_current()
        return current


@dataclass(frozen=True)
class Storage:
    root: Path
    namespace: str
    limit: int


def create_worker(secret: str, authority: AuthorityClient, models: Storage, frames: Storage,
                  signer: bytes, runtime: ModelRuntime | None) -> FastAPI:
    if hmac.compare_digest(secret.encode(), authority.token.encode()):
        raise ValueError('Ingress and authority credentials must be distinct')
    if len(signer) != 32 or not 1 <= models.limit <= 256 * 1024**2 or not 1 <= frames.limit <= 32 * 1024**2:
        raise ValueError('Invalid inference storage configuration')

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            authority.client.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    router = APIRouter(route_class=InternalRoute)
    active = Lock()

    def refresh(request: InferenceRequest, previous: LiveLease) -> LiveLease:
        previous.require_current()
        current = authority.get(request)
        if current.lease.evidence() != previous.lease.evidence():
            raise ValueError('Eligibility evidence changed')
        return current

    @router.post(INFERENCE_PATH, response_model=InferenceResponse, dependencies=[Depends(require_token(secret))])
    def infer(request: InferenceRequest):
        if not within_namespace(request.frame.object_key, frames.namespace):
            raise HTTPException(422, 'Invalid frame reference')
        if runtime is None or not active.acquire(blocking=False):
            raise HTTPException(503, 'Inference unavailable')
        try:
            started = time.monotonic()
            lease = authority.get(request)
            artifact = check_artifact(models.root, models.namespace, signer, lease.lease,
                                      models.limit, capture=True)
            if (artifact.manifest_sha256, artifact.signer_key_sha256) != (
                lease.lease.manifest_sha256, lease.lease.signer_key_sha256,
            ) or artifact.data is None:
                raise ValueError('Local provenance differs from verified evidence')
            frame = read_small(frames.root, request.frame.object_key, frames.limit)
            if not frame:
                raise ValueError('Frame is empty')
            lease = refresh(request, lease)
            lease.require_current()
            with runtime.load(artifact.data) as model:
                lease = refresh(request, lease)
                lease.require_current()
                detections = [Detection.model_validate(d) for d in runtime.infer(model, frame, request)]
            if any(d.bbox_xyxy[2] > request.frame.width or d.bbox_xyxy[3] > request.frame.height
                   for d in detections):
                raise ValueError('Detection is outside the frame')
            return InferenceResponse(
                request_id=request.request_id, frame_id=request.frame_id, model_key=request.model_key,
                model_version=request.model_version, inference_ms=(time.monotonic() - started) * 1000,
                detections=detections,
            )
        except Exception:
            # Avoid exposing upstream responses, local paths or adapter exception details.
            raise HTTPException(503, 'Inference unavailable') from None
        finally:
            active.release()

    app.include_router(router)
    return app


def mount(root: str, namespace: str, limit: str) -> Storage:
    path = Path(root)
    if not path.is_absolute() or not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise ValueError('Inference storage must use a read-only mount')
    if not within_namespace(namespace + '/check', namespace):
        raise ValueError('Invalid namespace')
    return Storage(path, namespace, int(limit))


def from_environment() -> FastAPI:
    url = httpx.URL(os.environ['ELIGIBILITY_AUTHORITY_URL'])
    schemes = {'https', 'http'} if os.environ.get('INFERENCE_ALLOW_LOCAL_HTTP') == 'true' else {'https'}
    if (url.scheme not in schemes or not url.host or url.userinfo or url.query or url.fragment
            or url.path not in ('', '/')):
        raise ValueError('Invalid eligibility authority URL')
    runtime = None
    if config := os.environ.get('INFERENCE_RUNTIME_FACTORY'):
        module, factory = config.split(':', 1)
        runtime = getattr(import_module(module), factory)()
    token = read_token(os.environ['ELIGIBILITY_TOKEN_FILE'])
    with Path(os.environ['INFERENCE_SIGNER_PUBLIC_KEY']).open('rb') as source:
        key = source.read(33)
    return create_worker(
        read_token(os.environ['INFERENCE_TOKEN_FILE']),
        AuthorityClient(httpx.Client(base_url=url, follow_redirects=False, trust_env=False, timeout=2), token),
        mount(os.environ['INFERENCE_MODEL_ROOT'], os.environ['MODEL_ARTIFACT_NAMESPACE'],
              os.environ['INFERENCE_MAX_MODEL_BYTES']),
        mount(os.environ['INFERENCE_FRAME_ROOT'], os.environ['INFERENCE_FRAME_NAMESPACE'],
              os.environ['INFERENCE_MAX_FRAME_BYTES']),
        key, runtime,
    )
