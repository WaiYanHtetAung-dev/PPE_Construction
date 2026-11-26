"""Opt-in Linux acceptance with real HTTPS, PostgreSQL and a worker subprocess."""

import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from statistics import median
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.responses import JSONResponse
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.camera_models import AssignmentInput, put_assignment
from app.assignment_snapshot import create_app, postgres_reader
from app.contracts.assignment_snapshot import SNAPSHOT_PATH, parse_snapshot_response
from app.db.models import Camera, CameraModelAssignment, ModelVersion, Organization, OrganizationMembership, Site, User
from app.model_artifact_integrity import Manifest
from app.scripts.gateway_credentials import provision, revoke, rotate
from app.scripts.model_artifact_verifier import verify_and_promote
from inference_worker.authority import create_authority, postgres_resolver
from inference_worker.contract import INFERENCE_PATH
from inference_worker.onnx_cpu import LABELS, detection
from media_gateway.assignment_resolver import AssignmentResolver, CameraScope
from media_gateway.frame_queue import FrameQueue
from media_gateway.inference_dispatch import DispatchError, InferenceDispatcher
from media_gateway.sampler import sample_camera
from media_gateway.video_source import local_video_source
from tests.media_decoder_integration import HEIGHT, WIDTH, generate_clip
from tests.synthetic_stack_support import listener, paced_video, readonly_bind, temporary_tls, wait_for, worker_process
from tests.test_onnx_cpu import fixture_graph
from tests.test_model_verification import role_connections

pytestmark = pytest.mark.skipif(os.getenv('PPE_STACK_RUN') != '1', reason='Use the isolated Linux stack CI command')

CLASS_MAP = {label: detection(i, 1.0, (1, 1, 2, 2)).class_key for i, label in enumerate(LABELS)}
FRAME_BYTES = WIDTH * HEIGHT * 3
REPEAT_CYCLES = 3
SAMPLING_COMPARISON_SECONDS = 12
SAMPLING_INTERVALS = (0.2, 0.3, 0.4)
SAMPLING_BLOCK_ORDERS = ((0.2, 0.3, 0.4), (0.3, 0.4, 0.2), (0.4, 0.2, 0.3))


def owner_engine():
    url = make_url(os.environ['PPE_DISPOSABLE_POSTGRES_URL'])
    assert sys.platform == 'linux' and os.environ.get('APP_ENV') == 'ci'
    assert (url.drivername, url.username, url.port, url.database) == ('postgresql+psycopg', 'ppe_ci', 5432, 'ppe_ci')
    assert url.host in ('127.0.0.1', 'postgres') and not url.query
    return create_engine(url, hide_parameters=True)


def readonly_reader(owner, grants):
    name, password = 'stack_' + uuid4().hex, uuid4().hex
    with owner.begin() as db:
        db.exec_driver_sql(f"CREATE ROLE {name} LOGIN PASSWORD '{password}'")
        for grant in grants:
            db.exec_driver_sql(f'GRANT SELECT {grant} TO {name}')
    return create_engine(owner.url.set(username=name, password=password), hide_parameters=True,
                         connect_args={'options': '-c default_transaction_read_only=on -c statement_timeout=1500'})


def seed(owner, model_root, signer):
    with owner.begin() as db:
        if db.scalar(text("SELECT to_regrole('ppe_assignment_operator')")) is None:
            db.execute(text('CREATE ROLE ppe_assignment_operator NOLOGIN'))
    with Session(owner, expire_on_commit=False) as db, db.begin():
        org = Organization(name='Disposable stack organization')
        admin = User(email=f'{uuid4().hex}@example.invalid', password_hash='unused-synthetic-identity')
        db.add_all([org, admin])
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=admin.id, role='admin'))
        cameras, models = [], []
        for index in range(3):
            site = Site(organization_id=org.id, name=f'Synthetic site {index}')
            db.add(site)
            db.flush()
            camera = Camera(site_id=site.id, name=f'Synthetic camera {index}', stream_ref=f'stream:stack/{index}')
            db.add(camera)
            db.flush()
            cameras.append(CameraScope(UUID(org.id), UUID(site.id), UUID(camera.id)))
        for label in ('a', 'b'):
            data = fixture_graph(empty=label == 'b')
            model = ModelVersion(model_key=f'stack-{label}-{uuid4().hex}', version='1',
                                 artifact_ref=f'synthetic/{label}.onnx', class_map=CLASS_MAP,
                                 artifact_sha256=hashlib.sha256(data).hexdigest())
            db.add(model)
            db.flush()
            (model_root / model.artifact_ref).write_bytes(data)
            sign_manifest(model_root, model, signer)
            models.append(model)
        principal = provision(db, org.id, {str(item.camera_id): str(item.site_id) for item in cameras})
        token = rotate(db, principal)
    return cameras, models, principal, token, admin.id


def sign_manifest(root, model, signer):
    now = datetime.now(UTC)
    payload = Manifest(model_version_id=UUID(model.id), model_key=model.model_key, version=model.version,
                       artifact_ref=model.artifact_ref, artifact_sha256=model.artifact_sha256,
                       release_id=f'test-{uuid4().hex}', issued_at=now,
                       expires_at=now + timedelta(minutes=15)).model_dump_json().encode()
    artifact = root / model.artifact_ref
    artifact.with_suffix('.onnx.manifest.json').write_bytes(payload)
    artifact.with_suffix('.onnx.manifest.sig').write_bytes(signer.sign(payload))


class MeasuredTransport(httpx.AsyncHTTPTransport):
    """Still uses real sockets and certificate verification. Can hold one real reply."""

    def __init__(self, ssl_context):
        super().__init__(verify=ssl_context, trust_env=False)
        self.starts = []
        self.latencies = []
        self.cancelled = 0
        self.received, self.release = asyncio.Event(), asyncio.Event()
        self.hold = False
        self.hold_model = None

    async def handle_async_request(self, request):
        assert request.url.scheme == 'https' and request.url.host == '127.0.0.1'
        started = monotonic()
        body = json.loads(request.content)
        self.starts.append((started, body.get('camera_id', body.get('model_key'))))
        try:
            response = await super().handle_async_request(request)
            self.latencies.append(monotonic() - started)
            if self.hold and (self.hold_model is None or body.get('model_key') == self.hold_model):
                self.received.set()
                try:
                    await self.release.wait()
                except BaseException:
                    await response.aclose()
                    raise
            return response
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


class MeasuredQueue(FrameQueue):
    def __init__(self):
        super().__init__(max_cameras=3, max_bytes=3 * FRAME_BYTES, max_frame_bytes=FRAME_BYTES)
        self.offers = Counter()
        self.taken = Counter()
        self.losses = Counter()
        self.purges = Counter()
        self.revoking = set()
        self.inference_busy = False
        self.response_held = lambda: False

    def offer(self, frame):
        camera = frame.camera_id
        self.offers[camera] += 1
        pending_before = camera in self._pending
        purges_before = self.purges[camera]
        admitted = super().offer(frame)
        if not admitted:
            # The fixtures are fixed-size and the queue has exactly one full slot per camera.
            assert len(frame.data) == FRAME_BYTES
            self.losses[camera, 'policy_rejected'] += 1
        elif pending_before and self.purges[camera] == purges_before:
            reason = ('replacement_held_response' if self.response_held() else
                      'replacement_dispatch_busy' if self.inference_busy else 'replacement_idle')
            self.losses[camera, reason] += 1
        return admitted

    def discard(self, camera_id):
        pending = camera_id in self._pending
        super().discard(camera_id)
        if pending:
            self.purges[camera_id] += 1
            reason = 'purge_during_revocation' if camera_id in self.revoking else 'purge_other'
            self.losses[camera_id, reason] += 1

    def take(self):
        frame = super().take()
        if frame is not None:
            self.taken[frame.camera_id] += 1
        return frame


def test_postgres_synthetic_https_assignment_stack(tmp_path):
    with TemporaryDirectory(dir=tmp_path) as directory:
        asyncio.run(exercise_stack(Path(directory)))
    assert not Path(directory).exists()


async def exercise_stack(root):
    owner = owner_engine()
    models_source, frames_source = root / 'model-source', root / 'frame-source'
    (models_source / 'synthetic').mkdir(parents=True)
    (frames_source / 'frames').mkdir(parents=True)
    signer = Ed25519PrivateKey.generate()
    public_key = signer.public_key().public_bytes_raw()
    context, cert, key, ca_file = temporary_tls(root)
    scopes, (model_a, model_b), principal, token, admin_id = seed(owner, models_source, signer)
    governance = role_connections(owner)
    cameras = tuple(str(scope.camera_id) for scope in scopes)
    assignment_db = readonly_reader(owner, ['ON public.gateway_snapshot_credentials, public.gateway_snapshot_assignments'])
    eligibility_db = readonly_reader(owner, [
        'ON public.eligible_model_versions',
        '(id,model_key,version,artifact_ref,artifact_sha256) ON public.model_versions',
        '(id,model_version_id,manifest_sha256,signer_key_sha256,expires_at) ON public.model_verifications',
    ])
    try:
        async with AsyncExitStack() as stack:
            model_mount = stack.enter_context(readonly_bind(models_source, root / 'worker-models'))
            frame_mount = stack.enter_context(readonly_bind(frames_source, root / 'worker-frames'))
            with Session(governance['verifier']) as db, db.begin():
                for model in (model_a, model_b):
                    verify_and_promote(db, model.id, model_mount, 'synthetic', public_key, 1024**2)
            with Session(owner) as db, db.begin():
                for camera, model in zip(cameras, (model_a, model_a, model_b)):
                    db.add(CameraModelAssignment(camera_id=camera, model_version_id=model.id))
            with assignment_db.begin() as db, pytest.raises(DBAPIError):
                db.execute(text('UPDATE public.gateway_principals SET disabled_at = now()'))

            availability = {'stall': False}
            denial_events = []
            control_app = create_app(postgres_reader(assignment_db))

            async def control(scope, receive, send):
                if scope['type'] == 'http' and availability['stall']:
                    await asyncio.sleep(2.25)
                    await JSONResponse({'detail': 'Synthetic outage'}, status_code=503)(scope, receive, send)
                else:
                    async def observe(message):
                        if (message['type'] == 'http.response.body'
                                and scope.get('path') == SNAPSHOT_PATH and message.get('body')):
                            payload = json.loads(message['body'])
                            if payload.get('decision') == 'revoked':
                                denial_events.append((monotonic(), payload['revoked_through_generation']))
                        await send(message)

                    await control_app(scope, receive, observe)

            authority_secret, worker_secret = token_urlsafe(32), token_urlsafe(32)
            authority_app = create_authority(authority_secret, postgres_resolver(eligibility_db, 5))
            control_url = await stack.enter_async_context(listener(control, cert, key))
            authority_url = await stack.enter_async_context(listener(authority_app, cert, key))
            settings = {'ELIGIBILITY_AUTHORITY_URL': authority_url, 'ELIGIBILITY_AUTHORITY_CA_FILE': str(ca_file),
                        'INFERENCE_RUNTIME_FACTORY':
                        'inference_worker.onnx_cpu:factory', 'MODEL_ARTIFACT_NAMESPACE': 'synthetic',
                        'INFERENCE_FRAME_NAMESPACE': 'frames', 'INFERENCE_MAX_MODEL_BYTES': str(1024**2),
                        'INFERENCE_MAX_FRAME_BYTES': str(1024**2), 'INFERENCE_MODEL_ROOT': str(model_mount),
                        'INFERENCE_FRAME_ROOT': str(frame_mount)}
            for env, data in (('ELIGIBILITY_TOKEN_FILE', authority_secret.encode()),
                              ('INFERENCE_TOKEN_FILE', worker_secret.encode()), ('INFERENCE_SIGNER_PUBLIC_KEY', public_key)):
                path = root / env.lower()
                path.touch(mode=0o600, exist_ok=False)
                path.write_bytes(data)
                settings[env] = str(path)
            worker = await stack.enter_async_context(worker_process(cert, key, settings, context))
            await verify_stack(stack, root, owner, context, control_url, worker, worker_secret, token,
                               principal, scopes, (model_a, model_b), frames_source, models_source, model_mount,
                               signer, availability, governance, admin_id, denial_events)
    finally:
        eligibility_db.dispose()
        assignment_db.dispose()
        for engine in governance.values():
            engine.dispose()
        owner.dispose()


async def verify_stack(stack, root, owner, context, control_url, worker, worker_secret, token,
                       principal, scopes, models, frames_source, models_source, model_mount, signer, availability,
                       governance, admin_id, denial_events):
    camera_ids = [str(scope.camera_id) for scope in scopes]
    first, second, third = camera_ids
    model_a, model_b = models
    worker_url = worker.origin
    queue = MeasuredQueue()
    control_transport, worker_transport = MeasuredTransport(context), MeasuredTransport(context)
    client = await stack.enter_async_context(httpx.AsyncClient(verify=context, trust_env=False, timeout=2))

    async def snapshot(scope, credential=token, **changes):
        body = {'schema_version': '1.0', 'organization_id': str(scope.organization_id),
                'site_id': str(scope.site_id), 'camera_id': str(scope.camera_id), 'nonce': str(uuid4())} | changes
        headers = {'Authorization': f'Bearer {credential}'} if credential else {}
        return await client.post(control_url + SNAPSHOT_PATH, json=body, headers=headers)

    async with httpx.AsyncClient(trust_env=False, timeout=2) as untrusted:
        with pytest.raises(httpx.ConnectError, match='CERTIFICATE_VERIFY_FAILED'):
            await untrusted.get(control_url)
    assert (await snapshot(scopes[0], None)).status_code == 401
    assert (await snapshot(scopes[0], f'{uuid4()}.{token_urlsafe(32)}')).status_code == 401
    assert (await snapshot(scopes[0], organization_id=str(uuid4()))).status_code == 404
    assert (await snapshot(scopes[0], nonce='bad')).status_code == 422
    assert (await client.post(control_url + SNAPSHOT_PATH, content=b' ' * 2049,
                              headers={'Authorization': f'Bearer {token}'})).status_code == 413
    with Session(owner) as db, db.begin():
        new_token = rotate(db, principal)
    assert (await snapshot(scopes[0], new_token)).status_code == 200
    with Session(owner) as db, db.begin():
        revoke(db, principal, token.split('.')[0])
    assert (await snapshot(scopes[0])).status_code == 401

    resolver = await stack.enter_async_context(AssignmentResolver(
        queue, scopes, control_origin=control_url, token=new_token, supported_class_maps=[CLASS_MAP],
        transport=control_transport,
    ))
    dispatcher = await stack.enter_async_context(InferenceDispatcher(
        queue, resolver, frames_source, worker_origin=worker_url, token=worker_secret,
        transport=worker_transport, timeout=10,
    ))
    paths = {}
    for camera, fps in zip(camera_ids, (10, 24, 30)):
        paths[camera] = root / f'clip-{fps}.mp4'
        generate_clip(paths[camera], fps)

    async def sample(camera):
        before = queue.offers[camera]
        task = asyncio.create_task(sample_camera(camera, lambda: local_video_source(paths[camera]), queue,
                                                  sample_interval=0.2, frame_timeout=4,
                                                  retry_initial=15, retry_max=15))
        try:
            await wait_for(lambda: queue.offers[camera] > before, 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    emissions = []

    async def next_frame():
        result = await dispatcher.dispatch_one()
        assert result is not None
        emissions.append((result.response.model_key, monotonic()))
        return result

    async def check_cameras(assignments):
        await asyncio.gather(*(sample(camera) for camera in camera_ids))
        results = [await next_frame() for _ in camera_ids]
        assert len({result.response.request_id for result in results}) == 3
        assert len({result.response.frame_id for result in results}) == 3
        assert {result.frame.camera_id for result in results} == set(camera_ids)
        for result in results:
            camera = result.frame.camera_id
            model = assignments[camera]
            scope = next(item for item in scopes if str(item.camera_id) == camera)
            assert (result.assignment.camera_id, result.assignment.site_id, result.assignment.organization_id) == (
                scope.camera_id, scope.site_id, scope.organization_id)
            assert result.assignment.model_version_id == UUID(model.id)
            assert (result.response.model_key, result.response.model_version) == (model.model_key, model.version)
            assert result.frame.received_at.tzinfo == UTC and 0 <= result.frame.source_timestamp < 1
            assert result.frame.source_frame_index >= 0 and result.frame.sample_interval == 0.2
            assert bool(result.response.detections) == (model.id == model_a.id)
            assert all(CLASS_MAP[item.original_class] == item.class_key for item in result.response.detections)

    def switch_first(model, revision):
        with Session(governance['runtime']) as db:
            result = put_assignment(str(scopes[0].organization_id), scopes[0].camera_id,
                                    AssignmentInput(model_version_id=UUID(model.id), expected_revision=revision),
                                    db.get(User, admin_id), db)
        assert result.revision == revision + 1
        return monotonic()

    def revoke_model_a(generation):
        with Session(governance['revoker']) as db, db.begin():
            assert db.scalar(text('SELECT public.revoke_verified_model(:id)'), {'id': model_a.id}) == generation
        return monotonic()

    def promote_model_a():
        sign_manifest(models_source, model_a, signer)
        with Session(governance['verifier']) as db, db.begin():
            generation = verify_and_promote(db, model_a.id, model_mount, 'synthetic',
                                            signer.public_key().public_bytes_raw(), 1024**2)
        return generation, monotonic()

    assert all(await asyncio.gather(*(resolver.refresh(camera) for camera in camera_ids)))
    poll = asyncio.create_task(resolver.run())
    stack.push_async_callback(cancel_poll, poll)
    await check_cameras(dict(zip(camera_ids, (model_a, model_a, model_b))))
    await sample(first)
    switch_at = switch_first(model_b, 0)
    await wait_for(lambda: resolver.current(first) is not None and
                   resolver.current(first).assignment.model_version_id == UUID(model_b.id), 7)
    switch_delay = monotonic() - switch_at
    assert switch_delay <= 7 and queue.take() is None
    await check_cameras(dict(zip(camera_ids, (model_b, model_a, model_b))))

    await sample(second)
    worker_transport.hold = True
    inflight = asyncio.create_task(dispatcher.dispatch_one())
    try:
        await asyncio.wait_for(worker_transport.received.wait(), 4)
        prior = resolver.current(second)
        revoked_at = revoke_model_a(prior.generation)
        denial = parse_snapshot_response((await snapshot(scopes[1], new_token)).content)
        assert denial.decision == 'revoked' and denial.assignment_revision == prior.revision
        assert denial.revoked_through_generation == prior.generation
        await wait_for(lambda: resolver.current(second) is None, 7)
        revoke_delay = monotonic() - revoked_at
        assert revoke_delay <= 7
    finally:
        worker_transport.hold = False
        worker_transport.release.set()
        with pytest.raises(DispatchError, match='assignment_invalidated'):
            await inflight
    before = len(worker_transport.starts)
    await sample(second)
    assert await dispatcher.dispatch_one() is None
    assert len(worker_transport.starts) == before
    assert resolver.current(first) and resolver.current(third)
    assert list((frames_source / 'frames').iterdir()) == []

    image = frames_source / 'frames' / 'independent-probe.png'
    Image.new('RGB', (WIDTH, HEIGHT)).save(image)
    wire = {'schema_version': '1.0', 'request_id': str(uuid4()), 'frame_id': str(uuid4()),
            'model_key': model_a.model_key, 'model_version': model_a.version,
            'frame': {'object_key': 'frames/independent-probe.png', 'width': WIDTH,
                      'height': HEIGHT, 'content_type': 'image/png'}}
    try:
        assert (await client.post(worker_url + INFERENCE_PATH, json=wire)).status_code == 401
        independently = await client.post(worker_url + INFERENCE_PATH, json=wire,
                                          headers={'Authorization': f'Bearer {worker_secret}'})
        assert independently.status_code == 503
    finally:
        image.unlink()

    await cancel_poll(poll)
    periods = []
    for camera in camera_ids:
        starts = [at for at, camera_id in control_transport.starts if camera_id == camera]
        periods.extend(b - a for a, b in zip(starts, starts[1:]))
    assert await resolver.refresh(first) and await resolver.refresh(third)
    cached = resolver.current(third)
    availability['stall'] = True
    timeout_at = monotonic()
    assert not await resolver.refresh(first)
    timeout_delay = monotonic() - timeout_at
    assert 1.8 <= timeout_delay < 3 and resolver.current(first) is None
    assert resolver.current(third) is not None
    await wait_for(lambda: resolver.current(third) is None, 10)
    expired_at = monotonic()
    assert cached.expires <= expired_at
    await sample(third)
    assert await dispatcher.dispatch_one() is None

    availability['stall'] = False
    restored_at = monotonic()
    generation, _ = promote_model_a()
    assert generation > prior.generation and await resolver.refresh(second)
    recovery_delay = monotonic() - restored_at
    recovered = resolver.current(second)
    assert recovered.revision == prior.revision and recovered.generation == generation
    await sample(second)
    assert (await next_frame()).response.detections
    assert queue.take() is None
    assert list((frames_source / 'frames').iterdir()) == []
    last_old_send = max(at for at, model in worker_transport.starts if model == model_a.model_key and at < restored_at)
    last_old_emit = max(at for model, at in emissions if model == model_a.model_key and at < restored_at)
    assert last_old_send < revoked_at and last_old_emit < revoked_at
    print('PPE_STACK_METRICS ' + json.dumps({
        'switch_to_observed_s': round(switch_delay, 3), 'revoke_to_observed_s': round(revoke_delay, 3),
        'last_old_send_relative_to_revoke_s': round(last_old_send - revoked_at, 3),
        'last_old_emit_relative_to_revoke_s': round(last_old_emit - revoked_at, 3),
        'outage_timeout_s': round(timeout_delay, 3), 'poll_timeouts': control_transport.cancelled,
        'cached_expiry_after_outage_start_s': round(expired_at - timeout_at, 3),
        'poll_intervals_over_5s': sum(interval > 5 for interval in periods),
        'missed_full_poll_slots': sum(max(0, int(interval / 5) - 1) for interval in periods),
        'recovery_to_snapshot_s': round(recovery_delay, 3),
        'inference_responses_ms': [round(value * 1000, 2) for value in worker_transport.latencies],
        'camera_samples_offered': [queue.offers[camera] for camera in camera_ids],
        'camera_samples_dropped_before_dispatch': [queue.offers[camera] - queue.taken[camera] for camera in camera_ids],
    }, sort_keys=True))

    revision = 1
    for paced in (False, True):
        if paced:
            switch_first(model_b, revision)
            revision += 1
        async with asyncio.timeout(100):
            revision = await run_repeated_cycles(
                resolver, dispatcher, queue, paths, control_transport, worker_transport,
                model_a, model_b, switch_first, revoke_model_a, promote_model_a, denial_events,
                revision=revision, paced=paced,
            )
    trials = []
    for block, order in enumerate(SAMPLING_BLOCK_ORDERS, 1):
        for position, interval in enumerate(order, 1):
            async with asyncio.timeout(30):
                trial = await compare_sampling_interval(resolver, dispatcher, queue, paths, interval)
            trial.update(block=block, position=position)
            trials.append(trial)
            print('PPE_STACK_SAMPLING ' + json.dumps(trial, sort_keys=True))
    print('PPE_STACK_SAMPLING_BLOCKS ' + json.dumps(summarize_sampling_trials(trials), sort_keys=True))
    transport = httpx.AsyncHTTPTransport(verify=context, trust_env=False,
                                         limits=httpx.Limits(max_keepalive_connections=0))
    async with InferenceDispatcher(queue, resolver, frames_source, worker_origin=worker_url,
                                   token=worker_secret, transport=transport, timeout=1.5) as probe:
        await verify_worker_restart(worker, resolver, probe, queue, paths, frames_source / 'frames')
    assert list((frames_source / 'frames').iterdir()) == []


async def verify_worker_restart(worker, resolver, dispatcher, queue, paths, staged):
    """Restart the real TLS worker while all three paced sources keep sampling."""
    interval = 0.3
    assert all(await asyncio.gather(*(resolver.refresh(camera) for camera in paths)))

    def assignments():
        current = (resolver.current(camera) for camera in paths)
        bindings = []
        for active in current:
            assert active is not None
            bindings.append((active.assignment, active.revision, active.generation))
        return bindings

    async def results_by_camera():
        rows = {}
        async with asyncio.timeout(8):
            while len(rows) < len(paths):
                row = await dispatcher.dispatch_one()
                if row is None:
                    await asyncio.sleep(0.015)
                    continue
                camera = row.frame.camera_id
                active = resolver.current(camera, row.assignment_epoch)
                assert camera in paths and active and row.assignment == active.assignment
                assert row.frame.sample_interval == interval
                rows[camera] = row
        return rows

    active_before = assignments()
    clock = asyncio.get_running_loop().time
    async with asyncio.TaskGroup() as group:
        samplers = [group.create_task(sample_camera(
            camera, lambda path=path, fps=fps: paced_video(path, fps, lambda *_: None),
            queue, sample_interval=interval,
            frame_timeout=4, retry_initial=0.7, retry_max=1.4,
        )) for (camera, path), fps in zip(paths.items(), (10, 24, 30), strict=True)]
        poll = group.create_task(resolver.run())
        try:
            baseline = await results_by_camera()
            assert any(row.response.detections for row in baseline.values())
            await worker.stop()
            offers = queue.offers.copy()
            await wait_for(lambda: all(queue.offers[camera] > offers[camera] for camera in paths), 4)
            assert assignments() == active_before
            taken = queue.taken.total()
            failed_at = monotonic()
            with pytest.raises(DispatchError, match='^timeout$'):
                await dispatcher.dispatch_one()
            failure_delay = monotonic() - failed_at
            assert failure_delay < 3
            assert queue.taken.total() == taken + 1 and not list(staged.iterdir())

            restart_at = clock()
            await worker.start()
            ready_at = clock()
            offers = queue.offers.copy()
            await wait_for(lambda: all(queue.offers[camera] > offers[camera] for camera in paths), 4)
            recovered = await results_by_camera()
            recovery_delay = clock() - restart_at
            assert assignments() == active_before
            for camera, row in recovered.items():
                before = baseline[camera]
                assert row.frame.sampled_monotonic >= ready_at
                assert row.frame.source_frame_index > before.frame.source_frame_index
                assert row.response.request_id != before.response.request_id
                assert row.response.frame_id != before.response.frame_id
                assert row.response.detections == before.response.detections
        finally:
            for task in [poll, *samplers]:
                task.cancel()
    while queue.take() is not None:
        pass
    print('PPE_STACK_WORKER_RESTART ' + json.dumps({
        'sample_interval_s': interval, 'cameras_recovered': len(recovered),
        'outage_dispatch': 'timeout', 'outage_deadline_s': 1.5,
        'outage_dispatch_s': round(failure_delay, 3),
        'worker_tls_ready_s': round(ready_at - restart_at, 3),
        'restart_to_all_cameras_s': round(recovery_delay, 3),
    }, sort_keys=True))


def summarize_sampling_trials(trials):
    """Compare each interval against 0.2 s within the same balanced block."""
    by_interval = {interval: [trial for trial in trials if trial['sample_interval_s'] == interval]
                   for interval in SAMPLING_INTERVALS}
    metrics = ('emitted_fps', 'median_sample_to_result_ms', 'queue_replacements', 'source_fps')

    def sum_field(trial, field):
        return sum(camera[field] for camera in trial['cameras'])

    def delta(baseline, candidate):
        return {
            'interval_s': candidate['sample_interval_s'],
            'emitted_delta': sum_field(candidate, 'emitted') - sum_field(baseline, 'emitted'),
            'replacement_delta': sum_field(candidate, 'queue_replacements') - sum_field(baseline, 'queue_replacements'),
            'sample_age_delta_ms': [
                round(new['median_sample_to_result_ms'] - old['median_sample_to_result_ms'], 2)
                for old, new in zip(baseline['cameras'], candidate['cameras'], strict=True)
            ],
        }

    blocks = []
    for block, order in enumerate(SAMPLING_BLOCK_ORDERS, 1):
        windows = [trial for trial in trials if trial['block'] == block]
        assert tuple(trial['sample_interval_s'] for trial in windows) == order
        reference = next(trial for trial in windows if trial['sample_interval_s'] == 0.2)
        blocks.append({'block': block, 'order_s': order,
                       'deltas_from_02': [delta(reference, trial) for trial in windows if trial is not reference]})

    return {
        'blocks': blocks,
        'arms': [{
            'interval_s': interval, 'windows': len(arm),
            'total_emitted': sum(sum_field(trial, 'emitted') for trial in arm),
            'total_replacements': sum(sum_field(trial, 'queue_replacements') for trial in arm),
            'camera_window_medians': [
                {'input_target_fps': fps} | {
                    field: round(median(trial['cameras'][index][field] for trial in arm), 2)
                    for field in metrics
                }
                for index, fps in enumerate((10, 24, 30))
            ],
        } for interval, arm in by_interval.items()],
    }


async def compare_sampling_interval(resolver, dispatcher, queue, paths, interval):
    """Use the same eligible bindings and paced sources without artificial holds."""
    cameras = tuple(paths)
    assert all(await asyncio.gather(*(resolver.refresh(camera) for camera in cameras)))
    age_by_camera = {camera: [] for camera in cameras}
    source_frames = Counter()
    warmed = set()
    measuring = False
    clock = asyncio.get_running_loop().time

    def observe(camera):
        def record(_now, _gap):
            if measuring:
                source_frames[camera] += 1

        return record

    async def consume():
        while True:
            queue.inference_busy = True
            try:
                row = await dispatcher.dispatch_one()
            finally:
                queue.inference_busy = False
            if row is not None:
                camera = row.frame.camera_id
                active = resolver.current(camera, row.assignment_epoch)
                assert active and row.assignment == active.assignment
                assert row.frame.sample_interval == interval
                warmed.add(camera)
                if measuring:
                    age = clock() - row.frame.sampled_monotonic
                    assert age >= 0
                    age_by_camera[camera].append(age)
            await asyncio.sleep(0.02)

    tasks = [asyncio.create_task(resolver.run()), asyncio.create_task(consume())]
    for (camera, path), fps in zip(paths.items(), (10, 24, 30), strict=True):
        record = observe(camera)
        tasks.append(asyncio.create_task(sample_camera(
            camera, lambda path=path, fps=fps, record=record: paced_video(path, fps, record), queue,
            sample_interval=interval, frame_timeout=4, retry_initial=0.7, retry_max=1.4,
        )))
    try:
        await wait_for(lambda: len(warmed) == len(cameras), 6)
        await asyncio.sleep(3)
        before_offers, before_losses = queue.offers.copy(), queue.losses.copy()
        started = clock()
        measuring = True
        await asyncio.sleep(SAMPLING_COMPARISON_SECONDS)
        elapsed = clock() - started
        measuring = False
        offers, losses = queue.offers - before_offers, queue.losses - before_losses
        assert all(age_by_camera.values())
        assert not any(reason == 'replacement_held_response' for _, reason in losses)
    finally:
        for task in tasks:
            task.cancel()
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                raise result
        while queue.take() is not None:
            pass

    return {
        'sample_interval_s': interval,
        'measurement_s': round(elapsed, 3),
        'cameras': [{
            'input_target_fps': fps,
            'source_fps': round(source_frames[camera] / elapsed, 2),
            'offered': offers[camera],
            'emitted': len(age_by_camera[camera]),
            'emitted_fps': round(len(age_by_camera[camera]) / elapsed, 2),
            'median_sample_to_result_ms': round(median(age_by_camera[camera]) * 1000, 2),
            'max_sample_to_result_ms': round(max(age_by_camera[camera]) * 1000, 2),
            'queue_replacements': sum(losses[camera, reason] for reason in (
                'replacement_dispatch_busy', 'replacement_idle',
            )),
            'policy_rejections': losses[camera, 'policy_rejected'],
            'queue_purges': losses[camera, 'purge_other'],
        } for camera, fps in zip(cameras, (10, 24, 30), strict=True)],
    }


async def run_repeated_cycles(resolver, dispatcher, queue, paths, control, worker,
                              model_a, model_b, switch_first, revoke_model_a, promote_model_a, denial_events,
                              *, revision, paced):
    """Keep three decoders and the real inference consumer active across repeated changes."""
    cameras = list(paths)
    first, second, _ = cameras
    assert all(await asyncio.gather(*(resolver.refresh(camera) for camera in cameras)))
    before_offers, before_taken, before_losses = queue.offers.copy(), queue.taken.copy(), queue.losses.copy()
    first_latency, first_poll = len(worker.latencies), len(control.starts)
    initial_timeouts = control.cancelled
    run_started = monotonic()
    emitted, errors = Counter(), Counter()
    last_result = {}
    source_stats = {}
    queue.response_held = lambda: worker.hold and worker.received.is_set() and not worker.release.is_set()

    async def consume():
        while True:
            queue.inference_busy = True
            try:
                row = await dispatcher.dispatch_one()
            except DispatchError as error:
                if error.code not in ('assignment_invalidated', 'unavailable'):
                    raise
                errors[error.code] += 1
            else:
                if row is not None:
                    camera = row.frame.camera_id
                    active = resolver.current(camera, row.assignment_epoch)
                    assert active and row.assignment == active.assignment
                    assert bool(row.response.detections) == (row.response.model_key == model_a.model_key)
                    emitted[camera] += 1
                    last_result[camera] = (row.response.model_key, active.generation)
            finally:
                queue.inference_busy = False
            await asyncio.sleep(0.02)

    def source_observer(camera, fps):
        stats = source_stats[camera] = {'count': 0, 'first': None, 'last': None, 'min_gap': None}

        def observe(now, gap):
            stats['count'] += 1
            if stats['first'] is None:
                stats['first'] = now
            stats['last'] = now
            if gap is not None:
                assert gap >= 0.95 / fps
                previous = stats['min_gap']
                stats['min_gap'] = gap if previous is None else min(previous, gap)

        return observe

    tasks = [asyncio.create_task(resolver.run()), asyncio.create_task(consume())]
    for (camera, path), fps in zip(paths.items(), (10, 24, 30), strict=True):
        if paced:
            observe = source_observer(camera, fps)
            source = lambda path=path, fps=fps, observe=observe: paced_video(path, fps, observe)
        else:
            source = lambda path=path: local_video_source(path)
        tasks.append(asyncio.create_task(sample_camera(
            camera, source, queue,
            sample_interval=0.2, frame_timeout=4, retry_initial=0.7, retry_max=1.4,
        )))

    cycles = []
    try:
        await wait_for(lambda: all(emitted[camera] > 0 for camera in cameras))
        for cycle in range(REPEAT_CYCLES):
            target = model_a if cycle % 2 == 0 else model_b
            affected = [first, second] if target is model_a else [second]
            unaffected = [camera for camera in cameras if camera not in affected]
            switched_at = switch_first(target, revision)
            revision += 1
            await wait_for(lambda: resolver.current(first) is not None and
                           resolver.current(first).revision == revision, 7)
            switch_delay = monotonic() - switched_at
            assert resolver.current(first).assignment.model_version_id == UUID(target.id)
            await wait_for(lambda: last_result.get(first, (None,))[0] == target.model_key, 3)
            previous = resolver.current(second)
            assert previous is not None

            worker.received.clear()
            worker.release.clear()
            worker.hold_model, worker.hold = model_a.model_key, True
            try:
                await asyncio.wait_for(worker.received.wait(), 4)
                queue.revoking.update(affected)
                revoked_at = revoke_model_a(previous.generation)
                await wait_for(lambda: any(at >= revoked_at and floor == previous.generation
                                           for at, floor in denial_events)
                               and all(resolver.current(camera) is None for camera in affected), 7)
                revoke_delay = monotonic() - revoked_at
                assert all(resolver.current(camera) is not None for camera in unaffected)
                fenced = errors['assignment_invalidated']
                old_requests = sum(model == model_a.model_key for _, model in worker.starts)
            finally:
                queue.revoking.clear()
                worker.hold = False
                worker.release.set()
            await wait_for(lambda: errors['assignment_invalidated'] > fenced, 3)
            unaffected_counts = {camera: emitted[camera] for camera in unaffected}
            await wait_for(lambda: all(emitted[camera] > count
                                       for camera, count in unaffected_counts.items()), 3)
            assert sum(model == model_a.model_key for _, model in worker.starts) == old_requests

            generation, promoted_at = promote_model_a()
            assert generation > previous.generation

            def recovered():
                return all((binding := resolver.current(camera)) is not None
                           and binding.generation == generation for camera in affected)

            await wait_for(recovered, 7)
            recovery_delay = monotonic() - promoted_at
            await wait_for(lambda: all(last_result.get(camera) == (model_a.model_key, generation)
                                       for camera in affected), 4)
            assert resolver.current(second).revision == previous.revision
            cycles.append({'switch_s': round(switch_delay, 3), 'revoke_s': round(revoke_delay, 3),
                           'recovery_s': round(recovery_delay, 3)})
        assert all(not task.done() for task in tasks)
    finally:
        live_timeouts = control.cancelled - initial_timeouts
        worker.hold = False
        worker.release.set()
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                raise result

    live_taken = queue.taken - before_taken
    offers = queue.offers - before_offers
    pending = Counter()
    while (frame := queue.take()) is not None:
        pending[frame.camera_id] += 1
    drops = [offers[camera] - live_taken[camera] - pending[camera] for camera in cameras]
    assert all(count >= 0 for count in drops)
    losses = queue.losses - before_losses
    by_camera = [{reason: count for (camera_id, reason), count in losses.items() if camera_id == camera}
                 for camera in cameras]
    assert [sum(counts.values()) for counts in by_camera] == drops
    revocations = [cycle['revoke_s'] for cycle in cycles]
    periods = []
    for camera in cameras:
        starts = [at for at, camera_id in control.starts[first_poll:] if camera_id == camera]
        periods.extend(b - a for a, b in zip(starts, starts[1:]))
    metrics = {
        'elapsed_s': round(monotonic() - run_started, 3), 'cycles': cycles,
        'revoke_median_s': median(revocations), 'revoke_max_s': max(revocations),
        'offered': [offers[camera] for camera in cameras],
        'dropped_before_dispatch': drops,
        'drop_breakdown': by_camera,
        'pending_on_stop': [pending[camera] for camera in cameras],
        'emitted': [emitted[camera] for camera in cameras],
        'invalidated_responses': errors['assignment_invalidated'],
        'worker_unavailable': errors['unavailable'],
        'poll_timeouts': live_timeouts,
        'poll_intervals_over_5s': sum(interval > 5 for interval in periods),
        'missed_full_poll_slots': sum(max(0, int(interval / 5) - 1) for interval in periods),
        'max_worker_header_ms': round(max(worker.latencies[first_latency:]) * 1000, 2),
    }
    if paced:
        metrics['paced_sources'] = [{
            'target_fps': fps, 'decoded_frames_released': source_stats[camera]['count'],
            'effective_fps': round((source_stats[camera]['count'] - 1)
                                   / (source_stats[camera]['last'] - source_stats[camera]['first']), 2),
            'min_interval_ms': round(source_stats[camera]['min_gap'] * 1000, 2),
        } for camera, fps in zip(cameras, (10, 24, 30), strict=True)]
    label = 'PPE_STACK_PACED' if paced else 'PPE_STACK_REPEATED'
    print(label + ' ' + json.dumps(metrics, sort_keys=True))
    return revision


async def cancel_poll(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
