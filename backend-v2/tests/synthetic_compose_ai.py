"""Seed and exercise the independent ONNX worker inside the synthetic lab."""

import argparse
import asyncio
import hashlib
import os
import signal
import socket
import ssl
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from traceback import extract_tb
from uuid import UUID, uuid4

from tests.synthetic_compose_ids import NORTH, NORTH_ALIAS, NORTH_CAMERA, PROBE_VIOLATION, SOUTH
from tests.synthetic_compose_media import HOST, LOCAL_READER, PATH, credential

CONTROL = Path('/lab/control')
WORKER = Path('/lab/worker')
VERIFIER = Path('/lab/verifier')
MODELS = Path('/lab/models')
FRAMES = Path('/lab/frames')
ASSIGNMENT_PORT, ELIGIBILITY_PORT, WORKER_PORT = 8446, 8447, 8448
MODEL_ID = '8b351059-d530-49d9-8b85-8bac94f01c06'
MODEL_KEY = 'synthetic-compose'
NAMESPACE = 'synthetic'
MAX_BYTES = 1024**2


def readers(engine, owner):
    from secrets import token_urlsafe

    from sqlalchemy import text

    # The target roles and statements are constants. Generated passwords use
    # only the URL-safe alphabet and cannot change the SQL syntax.
    grants = {
        'assignment': ['SELECT ON gateway_snapshot_credentials, gateway_snapshot_assignments'],
        'eligibility': [
            'SELECT ON eligible_model_versions',
            'SELECT (id,model_key,version,artifact_ref,artifact_sha256) ON model_versions',
            'SELECT (id,model_version_id,manifest_sha256,signer_key_sha256,expires_at) ON model_verifications',
        ],
        'verifier': [
            'SELECT ON model_versions',
            'EXECUTE ON FUNCTION public.promote_verified_model(text,text,text,text,text,timestamptz,timestamptz)',
        ],
        'incident_fixture': [
            'SELECT ON cameras, sites, incidents, incident_outbox',
            'INSERT ON incidents, incident_outbox',
        ],
        'outbox_fixture': [
            'SELECT ON incidents, incident_outbox',
            'UPDATE (attempts, published_at, retry_at) ON incident_outbox',
        ],
    }
    with engine.begin() as db:
        for role in ('ppe_model_verifier', 'ppe_assignment_operator'):
            if db.scalar(text('SELECT to_regrole(:role)'), {'role': role}) is None:
                db.exec_driver_sql(f'CREATE ROLE {role} NOLOGIN')
        db.exec_driver_sql('GRANT ppe_assignment_operator TO ppe_lab_owner')
        for name, permissions in grants.items():
            role, password = 'ppe_lab_' + name, token_urlsafe(32)
            if db.scalar(text('SELECT to_regrole(:role)'), {'role': role}) is None:
                db.exec_driver_sql(f'CREATE ROLE {role} NOLOGIN')
            db.exec_driver_sql(f"ALTER ROLE {role} LOGIN PASSWORD '{password}'")
            for permission in permissions:
                db.exec_driver_sql(f'GRANT {permission} TO {role}')
            url = owner.set(username=role, password=password)
            root = VERIFIER if name == 'verifier' else CONTROL
            (root / f'{name}.url').write_text(url.render_as_string(hide_password=False), encoding='ascii')
        db.exec_driver_sql('GRANT ppe_model_verifier TO ppe_lab_verifier')


def seed():
    from secrets import token_urlsafe

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.models import Camera, ModelVersion, Site
    from app.scripts.gateway_credentials import provision, rotate
    from tests.synthetic_assignment_stack import CLASS_MAP, sign_manifest
    from tests.synthetic_compose_seed import owner_url
    from tests.synthetic_stack_support import temporary_tls
    from tests.test_onnx_cpu import fixture_graph

    owner = owner_url()
    engine = create_engine(owner, hide_parameters=True)
    signer = Ed25519PrivateKey.generate()
    fixture = fixture_graph()
    digest = hashlib.sha256(fixture).hexdigest()
    try:
        readers(engine, owner)
        with Session(engine) as db, db.begin():
            camera = db.get(Camera, NORTH_CAMERA)
            site = db.get(Site, camera.site_id) if camera else None
            if not site or site.organization_id != NORTH or camera.stream_ref != NORTH_ALIAS:
                raise ValueError('Expected the lab camera and tenant')
            model = db.get(ModelVersion, MODEL_ID)
            if model is None:
                model = ModelVersion(id=MODEL_ID, model_key=MODEL_KEY, version='1',
                                     artifact_ref='synthetic/compose.onnx', artifact_sha256=digest,
                                     class_map=CLASS_MAP)
                db.add(model)
                db.flush()
            elif (model.model_key, model.version, model.artifact_ref, model.artifact_sha256, model.class_map) != (
                    MODEL_KEY, '1', 'synthetic/compose.onnx', digest, CLASS_MAP):
                raise ValueError('The lab model does not match the synthetic fixture')
            principal = provision(db, NORTH, {NORTH_CAMERA: site.id})
            (CONTROL / 'assignment.token').write_text(rotate(db, principal), encoding='ascii')
            (CONTROL / 'site.id').write_text(site.id, encoding='ascii')
            (MODELS / model.artifact_ref).write_bytes(fixture)
            sign_manifest(MODELS, model, signer, lifetime=timedelta(hours=1))
    finally:
        engine.dispose()
    with TemporaryDirectory(dir=WORKER) as directory:
        _, cert, key, ca = temporary_tls(Path(directory))
        for path in (cert, key, ca):
            for root in (CONTROL, WORKER):
                (root / path.name).write_bytes(path.read_bytes())
    public_key = signer.public_key().public_bytes_raw()
    (VERIFIER / 'signer.pub').write_bytes(public_key)
    (WORKER / 'signer.pub').write_bytes(public_key)
    eligibility_token, worker_token = (token_urlsafe(32) for _ in range(2))
    for root in (CONTROL, WORKER):
        (root / 'eligibility.token').write_text(eligibility_token, encoding='ascii')
        (root / 'worker.token').write_text(worker_token, encoding='ascii')
    print('PPE_COMPOSE_AI_SEED: signed fixture, scoped assignment and isolated database readers prepared')


def bind():
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import Session

    from app.db.models import CameraModelAssignment, ModelVerification
    from app.scripts.model_artifact_verifier import verify_and_promote
    from tests.synthetic_compose_seed import owner_url

    owner = owner_url()
    if not os.statvfs(MODELS).f_flag & os.ST_RDONLY:
        raise ValueError('The lab verifier must use the read-only model mount')
    engine = create_engine(owner, hide_parameters=True)
    try:
        with Session(engine) as db:
            active = db.scalar(text('SELECT model_version_id FROM eligible_model_versions WHERE model_version_id=:id'),
                               {'id': MODEL_ID})
            latest = db.scalar(select(ModelVerification.manifest_sha256).where(
                ModelVerification.model_version_id == MODEL_ID
            ).order_by(ModelVerification.id.desc()).limit(1))
            manifest = MODELS / 'synthetic/compose.onnx.manifest.json'
            reuse = active and latest == hashlib.sha256(manifest.read_bytes()).hexdigest()
        if not reuse:
            verification = create_engine((VERIFIER / 'verifier.url').read_text(encoding='ascii'), hide_parameters=True)
            try:
                with Session(verification) as db, db.begin():
                    verify_and_promote(db, MODEL_ID, MODELS, NAMESPACE,
                                       (VERIFIER / 'signer.pub').read_bytes(), MAX_BYTES)
            finally:
                verification.dispose()
        with Session(engine) as db, db.begin():
            if (binding := db.get(CameraModelAssignment, NORTH_CAMERA)) is None:
                db.add(CameraModelAssignment(camera_id=NORTH_CAMERA, model_version_id=MODEL_ID))
            elif binding.model_version_id != MODEL_ID:
                raise ValueError('The lab camera assignment was changed')
    finally:
        engine.dispose()
    print('PPE_COMPOSE_AI_VERIFY: signed synthetic model verified and assigned')


async def control():
    from app.assignment_snapshot import from_environment as assignments
    from inference_worker.authority import from_environment as eligibility
    from tests.synthetic_stack_support import listener

    cert, key = CONTROL / 'listener.pem', CONTROL / 'listener.key'
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    async with listener(assignments(), cert, key, port=ASSIGNMENT_PORT), \
            listener(eligibility(), cert, key, port=ELIGIBILITY_PORT):
        await stop.wait()


def fixture_engine(role):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    if os.environ.get('APP_ENV') != 'synthetic-compose' or role not in {'incident_fixture', 'outbox_fixture'}:
        raise ValueError('Invalid lab fixture database role')
    url = make_url((CONTROL / f'{role}.url').read_text(encoding='ascii'))
    if (url.query or (url.drivername, url.username, url.host, url.port, url.database) !=
            ('postgresql+psycopg', f'ppe_lab_{role}', 'postgres', 5432, 'ppe_lab')):
        raise ValueError('Probe requires the isolated lab database role')
    return create_engine(url, hide_parameters=True, connect_args={
        'connect_timeout': 2, 'options': '-c statement_timeout=2000',
    })


async def record_probe_incident(row):
    """Exercise existing ingestion with an explicitly confirmed test event."""
    from secrets import token_urlsafe

    import httpx
    from sqlalchemy.orm import Session

    from app.db.models import IncidentOutbox
    from app.db.session import get_db
    from app.incident_ingestion import create_ingestion

    engine = fixture_engine('incident_fixture')
    secret = token_urlsafe(32)
    ingest = create_ingestion(secret)

    def lab_session():
        with Session(engine) as db:
            yield db

    ingest.dependency_overrides[get_db] = lab_session
    event_id = str(uuid4())
    event = {'event_id': event_id, 'organization_id': str(row.assignment.organization_id),
             'site_id': str(row.assignment.site_id), 'camera_id': row.frame.camera_id,
             'detected_at': row.frame.received_at.isoformat(), 'violation_type': PROBE_VIOLATION}
    path = '/internal/v1/incidents'
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ingest),
                                     base_url='http://synthetic-ingest') as client:
            assert (await client.post(path, json=event)).status_code == 401
            headers = {'Authorization': 'Bearer ' + secret}
            assert (await client.post(path, json=event | {'organization_id': SOUTH},
                                      headers=headers)).status_code == 404
            created = await client.post(path, json=event, headers=headers)
            repeated = await client.post(path, json=event, headers=headers)
            assert created.status_code == 201 and repeated.status_code == 200
            assert created.json()['incident_id'] == repeated.json()['incident_id']
            assert (await client.post(path, json=event | {'violation_type': 'synthetic_conflict'},
                                      headers=headers)).status_code == 409
        with Session(engine) as db:
            outbox = db.get(IncidentOutbox, event_id)
            assert outbox and outbox.incident_id == created.json()['incident_id']
    finally:
        engine.dispose()
    print('PPE_COMPOSE_INCIDENT: controlled synthetic event and retry map to one incident and outbox row')


async def probe(*, emit_incident=False):
    import httpx

    from inference_worker.contract import INFERENCE_PATH
    from media_gateway.assignment_resolver import AssignmentResolver, CameraScope
    from media_gateway.frame_queue import FrameQueue
    from media_gateway.inference_dispatch import InferenceDispatcher
    from media_gateway.network_source import central_rtsp_source
    from media_gateway.sampler import sample_camera
    from tests.synthetic_assignment_stack import CLASS_MAP

    trust = ssl.create_default_context(cafile=str(CONTROL / 'ca.pem'))
    worker_origin = f'https://{HOST}:{WORKER_PORT}'
    scope = CameraScope(UUID(NORTH), UUID((CONTROL / 'site.id').read_text(encoding='ascii')), UUID(NORTH_CAMERA))
    source = central_rtsp_source(HOST, LOCAL_READER, PATH, 'reader', credential('READER_PASSWORD'))
    frame_bytes = 160 * 64 * 3
    queue = FrameQueue(max_cameras=1, max_bytes=frame_bytes, max_frame_bytes=frame_bytes)
    async with httpx.AsyncClient(verify=trust, trust_env=False, timeout=5) as client:
        request = {'schema_version': '1.0', 'request_id': str(uuid4()), 'frame_id': str(uuid4()),
                   'model_key': MODEL_KEY, 'model_version': '1',
                   'frame': {'object_key': 'frames/auth-probe.png', 'width': 160,
                             'height': 64, 'content_type': 'image/png'}}
        assert (await client.post(worker_origin + INFERENCE_PATH, json=request)).status_code == 401
    async with AssignmentResolver(
        queue, [scope], control_origin=f'https://{HOST}:{ASSIGNMENT_PORT}',
        token=(CONTROL / 'assignment.token').read_text(encoding='ascii'),
        supported_class_maps=[CLASS_MAP], transport=httpx.AsyncHTTPTransport(verify=trust, trust_env=False),
    ) as resolver, InferenceDispatcher(
        queue, resolver, FRAMES, worker_origin=worker_origin,
        token=(CONTROL / 'worker.token').read_text(encoding='ascii'),
        timeout=10, transport=httpx.AsyncHTTPTransport(verify=trust, trust_env=False),
    ) as dispatcher:
        assert await resolver.refresh(NORTH_CAMERA), 'Synthetic assignment was unavailable'
        poll = asyncio.create_task(resolver.run())
        sampling = asyncio.create_task(sample_camera(NORTH_CAMERA, source, queue, sample_interval=0.3,
                                                     frame_timeout=5, retry_initial=0.5, retry_max=1.5))
        try:
            async with asyncio.timeout(25):
                while (row := await dispatcher.dispatch_one()) is None:
                    await asyncio.sleep(0.02)
                assert (row.assignment.organization_id, row.assignment.site_id, row.assignment.camera_id) == (
                    scope.organization_id, scope.site_id, scope.camera_id)
                assert row.assignment.model_version_id == UUID(MODEL_ID)
                assert row.frame.camera_id == NORTH_CAMERA and row.frame.source_timestamp >= 0
                assert (row.response.model_key, row.response.model_version) == (MODEL_KEY, '1')
                assert row.response.detections
                assert all(CLASS_MAP[d.original_class] == d.class_key for d in row.response.detections)
                assert not list((FRAMES / 'frames').iterdir()), 'Staged frame was not cleaned up'
                print(f'PPE_COMPOSE_ONNX: {len(row.response.detections)} detections attributed to the lab camera')
        finally:
            for task in (poll, sampling):
                task.cancel()
            await asyncio.gather(poll, sampling, return_exceptions=True)
    if emit_incident:
        await record_probe_incident(row)


def check(*ports):
    for port in ports:
        with socket.create_connection((HOST, port), timeout=0.5):
            pass


def main():
    actions = {'seed': seed, 'bind': bind, 'control': lambda: asyncio.run(control()),
               'check-worker': lambda: check(WORKER_PORT),
               'check-control': lambda: check(ASSIGNMENT_PORT, ELIGIBILITY_PORT)}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=[*actions, 'probe'])
    parser.add_argument('--record-synthetic-incident', action='store_true')
    args = parser.parse_args()
    if args.record_synthetic_incident and args.action != 'probe':
        parser.error('--record-synthetic-incident requires probe')
    os.umask(0o077)
    try:
        if args.action == 'probe':
            asyncio.run(probe(emit_incident=args.record_synthetic_incident))
        else:
            actions[args.action]()
    except Exception as error:
        if args.action == 'probe':
            raise
        location = extract_tb(error.__traceback__)[-1]
        raise SystemExit(
            f'Synthetic ONNX service {args.action} failed '
            f'({type(error).__name__} at {Path(location.filename).name}:{location.lineno})'
        ) from None


if __name__ == '__main__':
    main()
