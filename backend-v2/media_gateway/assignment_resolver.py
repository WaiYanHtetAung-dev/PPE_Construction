"""Poll authorized camera snapshots and fence invalidated assignment epochs."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from math import isfinite
from uuid import UUID, uuid4

import httpx

from app.contracts.assignment_snapshot import (
    MAX_RESPONSE_BYTES, MAX_SNAPSHOT_LIFETIME, SNAPSHOT_PATH, SnapshotRequest, parse_snapshot_response,
)
from media_gateway.inference_dispatch import CameraAssignment

logger = logging.getLogger(__name__)
TOKEN = re.compile(r'[0-9a-f-]{36}\.[A-Za-z0-9_-]{43}', re.ASCII)


@dataclass(frozen=True)
class CameraScope:
    organization_id: UUID
    site_id: UUID
    camera_id: UUID


@dataclass(frozen=True)
class ResolvedAssignment:
    assignment: CameraAssignment
    revision: int
    generation: int
    epoch: int
    expires: float


@dataclass
class _Camera:
    scope: CameraScope
    epoch: int = 0
    revision: int = -1
    model: object = None
    active: ResolvedAssignment | None = None
    refreshing: bool = False


class AssignmentResolver:
    """Own one queue and its camera bindings on the same media event loop."""

    def __init__(self, queue, scopes, *, control_origin, token, supported_class_maps,
                 poll_interval=5, deadline=2, max_lifetime=10, transport=None, clock=None):
        origin = httpx.URL(control_origin)
        if (origin.scheme != 'https' or not origin.host or origin.userinfo or origin.query
                or origin.fragment or origin.path not in ('', '/')):
            raise ValueError('Snapshot listener must use a configured HTTPS origin')
        if (not all(isfinite(value) for value in (poll_interval, deadline, max_lifetime))
                or not 0 < deadline <= 2 or not deadline <= poll_interval <= 5
                or not 0 < max_lifetime <= MAX_SNAPSHOT_LIFETIME):
            raise ValueError('Invalid snapshot timing')
        if clock is None:
            if not hasattr(time, 'CLOCK_BOOTTIME'):
                raise ValueError('Assignment polling requires a suspend-inclusive clock')
            clock = lambda: time.clock_gettime(time.CLOCK_BOOTTIME)
        self._clock = clock
        self._cameras = {}
        for scope in scopes:
            key = str(scope.camera_id)
            if key in self._cameras or not all(isinstance(identifier, UUID) for identifier in (
                scope.organization_id, scope.site_id, scope.camera_id,
            )):
                raise ValueError('Invalid or duplicated camera scope')
            self._cameras[key] = _Camera(scope)
        if len({camera.scope.organization_id for camera in self._cameras.values()}) != 1:
            raise ValueError('Snapshot credential requires scope in one organization')
        self._profiles = {frozenset(mapping.items()) for mapping in supported_class_maps}
        if not self._profiles or frozenset() in self._profiles:
            raise ValueError('Supported class maps are required')
        self._queue = queue
        self._poll_interval, self._deadline, self._ttl = poll_interval, deadline, max_lifetime
        self._generation = {}
        self._floor = {}
        self._model_maps = {}
        self._credential_epoch = 0
        self._token = self._checked_token(token)
        queue.bind_assignments(self._admit)
        self._client = httpx.AsyncClient(base_url=origin, follow_redirects=False, trust_env=False,
                                         timeout=deadline, transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self._invalidate_credential()
        await self._client.aclose()

    @staticmethod
    def _checked_token(token):
        if not TOKEN.fullmatch(token):
            raise ValueError('Invalid snapshot credential format')
        return token

    def _invalidate(self, camera):
        if camera.active is not None:
            camera.epoch += 1
            camera.active = None
        self._queue.discard(str(camera.scope.camera_id))

    def _invalidate_credential(self):
        self._credential_epoch += 1
        for camera in self._cameras.values():
            self._invalidate(camera)

    def reload_credential(self, token):
        self._token = self._checked_token(token)
        self._invalidate_credential()

    def owns_queue(self, queue):
        return queue is self._queue

    def current(self, camera_id, assignment_epoch=None):
        camera = self._cameras.get(camera_id)
        if camera is None or camera.active is None:
            return None
        if self._clock() >= camera.active.expires:
            self._invalidate(camera)
            return None
        if assignment_epoch is not None and camera.active.epoch != assignment_epoch:
            return None
        return camera.active

    def _admit(self, camera_id):
        active = self.current(camera_id)
        return active.epoch if active else None

    def _apply(self, camera, snapshot, started):
        revision, model = snapshot.assignment_revision, snapshot.model
        if revision < camera.revision or (revision == camera.revision and model != camera.model):
            raise ValueError('Stale assignment identity')
        generation = snapshot.verification_generation
        if model is not None:
            key = model.model_version_id
            newest = self._generation.get(key, 0)
            floor = self._floor.get(key, 0)
            if (generation or 0) < newest or (snapshot.revoked_through_generation or 0) < floor:
                raise ValueError('Stale verification evidence')
            self._generation[key] = generation or 0
            self._floor[key] = snapshot.revoked_through_generation or 0
            for item in self._cameras.values():
                active = item.active
                if active is not None and active.assignment.model_version_id == key and (
                    active.generation < (generation or 0) or active.generation <= self._floor[key]
                ):
                    self._invalidate(item)

        camera.revision, camera.model = revision, model
        if snapshot.decision != 'eligible':
            self._invalidate(camera)
            return False
        class_map = frozenset(snapshot.class_map.items())
        if class_map not in self._profiles or self._model_maps.get(key, class_map) != class_map:
            raise ValueError('Incompatible class map')
        self._model_maps[key] = class_map
        expires = started + min(self._ttl, (snapshot.expires_at - snapshot.issued_at).total_seconds())
        if self._clock() >= expires:
            raise ValueError('Expired assignment')
        assignment = CameraAssignment(camera.scope.organization_id, camera.scope.site_id, camera.scope.camera_id,
                                      model.model_version_id, model.model_key, model.version, snapshot.class_map)
        active = self.current(str(camera.scope.camera_id))
        if active is None or (active.assignment, active.revision, active.generation) != (assignment, revision, generation):
            self._invalidate(camera)
            camera.epoch += 1
        camera.active = ResolvedAssignment(assignment, revision, generation, camera.epoch, expires)
        return True

    async def refresh(self, camera_id: str) -> bool:
        camera = self._cameras[camera_id]
        if camera.refreshing:
            return False
        camera.refreshing = True
        started, ticket = self._clock(), self._credential_epoch
        query = SnapshotRequest(schema_version='1.0', organization_id=camera.scope.organization_id,
                                site_id=camera.scope.site_id, camera_id=camera.scope.camera_id, nonce=uuid4())
        try:
            async with asyncio.timeout(self._deadline):
                async with self._client.stream('POST', SNAPSHOT_PATH, json=query.model_dump(mode='json'), headers={
                    'Authorization': f'Bearer {self._token}', 'Accept-Encoding': 'identity', 'Cache-Control': 'no-store',
                }) as response:
                    if ticket != self._credential_epoch:
                        return False
                    if response.status_code == 401:
                        self._invalidate_credential()
                        return False
                    if (response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity'
                            or response.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/json'):
                        raise ValueError('Invalid snapshot response')
                    body = bytearray()
                    async for piece in response.aiter_bytes():
                        if len(body) + len(piece) > MAX_RESPONSE_BYTES:
                            raise ValueError('Snapshot exceeds size limit')
                        body.extend(piece)
                snapshot = parse_snapshot_response(bytes(body))
                if ticket != self._credential_epoch:
                    return False
                if (any(getattr(snapshot, name) != value for name, value in query)
                        or self._clock() >= started + self._deadline):
                    raise ValueError('Invalid snapshot binding or deadline')
                return self._apply(camera, snapshot, started)
        except (ValueError, RecursionError, TimeoutError, httpx.HTTPError):
            if ticket == self._credential_epoch:
                self._invalidate(camera)
                logger.warning('assignment_refresh_failed', extra={'camera_id': camera_id})
            return False
        except asyncio.CancelledError:
            if ticket == self._credential_epoch:
                self._invalidate(camera)
            raise
        finally:
            camera.refreshing = False
            if not any(item.refreshing for item in self._cameras.values()):
                needed = {item.model.model_version_id for item in self._cameras.values() if item.model is not None}
                for key in self._generation.keys() - needed:
                    self._generation.pop(key)
                    self._floor.pop(key)
                    self._model_maps.pop(key, None)

    async def run(self):
        async def poll(camera_id, offset):
            await asyncio.sleep(offset)
            while True:
                started = self._clock()
                await self.refresh(camera_id)
                await asyncio.sleep(max(0, started + self._poll_interval - self._clock()))

        async with asyncio.TaskGroup() as group:
            for index, camera_id in enumerate(self._cameras):
                group.create_task(poll(camera_id, index * self._poll_interval / len(self._cameras)))
