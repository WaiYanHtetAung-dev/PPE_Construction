import hashlib
import os
import time
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from argon2 import PasswordHasher
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog, Camera, CameraModelAssignment, CameraModelHistory, ModelVerificationRevocation,
    Organization, OrganizationMembership, User, utcnow,
)
from app.db.session import get_db
from app.main import app as business_app
from inference_worker.authority import create_authority, postgres_resolver
from inference_worker.contract import INFERENCE_PATH, LEASE_PATH, ModelLease
from inference_worker.service import AuthorityClient, Storage, create_worker
from tests.model_fixtures import seed_verified_model
from tests.test_camera_models import seed_camera
from tests.test_model_verification import ARTIFACT, model_version, release

INGRESS = 'i' * 32
AUTHORITY = 'a' * 32
WORKER_AUTH = {'Authorization': f'Bearer {INGRESS}'}
LEASE_AUTH = {'Authorization': f'Bearer {AUTHORITY}'}
LINUX = pytest.mark.skipif(os.open not in os.supports_dir_fd, reason='Secure read-only mount reader requires POSIX')


class FakeRuntime:
    def __init__(self):
        self.loads = []
        self.calls = 0
        self.closed = 0
        self.delay = 0

    @contextmanager
    def load(self, data):
        self.loads.append(data)
        time.sleep(self.delay)
        try:
            yield data
        finally:
            self.closed += 1

    def infer(self, model, frame, request):
        assert model == ARTIFACT and frame == b'frame bytes'
        self.calls += 1
        return []


@pytest.fixture
def worker(tmp_path):
    signer = Ed25519PrivateKey.generate()
    public_key = signer.public_key().public_bytes_raw()
    model = model_version()
    artifact = release(tmp_path, model, signer)
    frame = tmp_path / 'frames/frame.jpg'
    frame.parent.mkdir()
    frame.write_bytes(b'frame bytes')
    payload = {
        'request_id': str(uuid4()), 'frame_id': 'camera-frame',
        'model_key': model.model_key, 'model_version': model.version,
        'frame': {'object_key': 'frames/frame.jpg', 'width': 10, 'height': 10, 'content_type': 'image/jpeg'},
    }
    state = {'reads': 0, 'mode': 'good'}
    cached = {}

    def resolve(request):
        state['reads'] += 1
        current = utcnow()
        mode = state['mode']
        if mode == 'revoked' or (mode == 'revoked-after-load' and state['reads'] == 3):
            return None
        if mode == 'replace-after-hash' and state['reads'] == 2:
            artifact.write_bytes(b'replacement after verification')
        if mode == 'replay' and cached:
            return cached['lease']
        lease = ModelLease(
            model_key=model.model_key,
            model_version='other' if mode == 'different-version' else model.version,
            nonce=request.nonce, model_version_id=model.id,
            artifact_ref='other/model.bin' if mode == 'other-namespace' else model.artifact_ref,
            artifact_sha256=model.artifact_sha256,
            manifest_sha256=hashlib.sha256(artifact.with_suffix('.bin.manifest.json').read_bytes()).hexdigest(),
            signer_key_sha256=hashlib.sha256(public_key).hexdigest(),
            verification_id=1,
            issued_at=current - timedelta(seconds=4) if mode == 'expired' else current,
            expires_at=current - timedelta(seconds=1) if mode == 'expired' else current + timedelta(
                seconds=0.4 if mode == 'expire-in-loader' else 5,
            ),
        )
        cached['lease'] = lease
        return lease

    with TestClient(create_authority(AUTHORITY, resolve)) as server:
        def transport(request):
            if state['mode'] == 'offline':
                raise httpx.ConnectError('Disconnected synthetic authority', request=request)
            return server.request(request.method, request.url.path, content=request.content,
                                  headers=dict(request.headers))

        runtime = FakeRuntime()
        app = create_worker(
            INGRESS, AuthorityClient(httpx.Client(base_url='https://authority.test',
                                                  transport=httpx.MockTransport(transport)), AUTHORITY),
            Storage(tmp_path, 'approved', 1024), Storage(tmp_path, 'frames', 1024), public_key, runtime,
        )
        with TestClient(app) as client:
            yield client, runtime, payload, artifact, state, server


@LINUX
def test_valid_artifact_load_and_inference(worker):
    client, runtime, payload, _, state, _ = worker
    response = client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH)
    assert response.status_code == 200
    assert response.json()['schema_version'] == '1.0'
    assert response.json()['request_id'] == payload['request_id']
    assert runtime.loads == [ARTIFACT] and runtime.calls == runtime.closed == 1
    assert state['reads'] == 3


@LINUX
@pytest.mark.parametrize('mutation', ['signature', 'digest', 'missing'])
def test_invalid_artifacts_never_reach_loader(worker, mutation):
    client, runtime, payload, path, _, _ = worker
    if mutation == 'signature':
        path.with_suffix('.bin.manifest.sig').write_bytes(b'x' * 64)
    elif mutation == 'digest':
        path.write_bytes(b'wrong digest')
    else:
        path.unlink()
    response = client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH)
    assert response.status_code == 503
    assert runtime.loads == [] and runtime.calls == 0


@LINUX
@pytest.mark.parametrize('mode', ['expired', 'revoked', 'offline', 'different-version', 'other-namespace', 'replay'])
def test_missing_or_invalid_eligibility_fails_closed(worker, mode):
    client, runtime, payload, _, state, _ = worker
    state['mode'] = mode
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 503
    assert runtime.loads == [] and runtime.calls == 0


@LINUX
def test_loader_sees_verified_snapshot_after_artifact_replacement(worker):
    client, runtime, payload, artifact, state, _ = worker
    state['mode'] = 'replace-after-hash'
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 200
    assert artifact.read_bytes() != ARTIFACT
    assert runtime.loads == [ARTIFACT]
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 503
    assert runtime.calls == 1


@LINUX
def test_confirmed_revocation_after_load_unloads_without_inference(worker):
    client, runtime, payload, _, state, _ = worker
    state['mode'] = 'revoked-after-load'
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 503
    assert runtime.loads == [ARTIFACT] and runtime.calls == 0 and runtime.closed == 1
    state['mode'] = 'revoked'
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 503
    assert runtime.loads == [ARTIFACT]


@LINUX
def test_lease_expiring_during_model_load_prevents_dispatch(worker):
    client, runtime, payload, _, state, _ = worker
    state['mode'] = 'expire-in-loader'
    runtime.delay = 0.55
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 503
    assert runtime.loads == [ARTIFACT] and runtime.calls == 0 and runtime.closed == 1
    assert state['reads'] == 2


@LINUX
def test_no_stale_lease_used_after_authority_disconnect(worker):
    client, runtime, payload, _, state, _ = worker
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 200
    state['mode'] = 'offline'
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 503
    assert runtime.calls == 1


def test_worker_and_authority_require_separate_credentials(worker):
    client, runtime, payload, _, state, authority = worker
    query = {'model_key': payload['model_key'], 'model_version': payload['model_version'], 'nonce': str(uuid4())}
    assert client.post(INFERENCE_PATH, json=payload).status_code == 401
    assert client.post(INFERENCE_PATH, json=payload, headers=LEASE_AUTH).status_code == 401
    assert authority.post(LEASE_PATH, json=query, headers=WORKER_AUTH).status_code == 401
    assert state['reads'] == 0 and runtime.loads == []


def test_worker_rejects_arbitrary_frame_urls(worker):
    client, runtime, payload, _, state, _ = worker
    payload['frame']['object_key'] = 'https://frames.invalid/file.jpg'
    assert client.post(INFERENCE_PATH, json=payload, headers=WORKER_AUTH).status_code == 422
    assert state['reads'] == 0 and runtime.loads == []


def test_postgres_authority_grants_live_evidence_and_business_only_rollback():
    url = os.environ.get('PPE_DISPOSABLE_POSTGRES_URL')
    if not url:
        pytest.skip('Set PPE_DISPOSABLE_POSTGRES_URL to a migrated disposable test database')
    owner = create_engine(url, hide_parameters=True)
    assert owner.dialect.name == 'postgresql'
    reader = None
    try:
        role, password = 'lease_' + uuid4().hex, uuid4().hex
        with owner.begin() as db:
            db.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
            db.exec_driver_sql(f'GRANT SELECT ON public.eligible_model_versions TO {role}')
            db.exec_driver_sql(f'GRANT SELECT (id,model_key,version,artifact_ref,artifact_sha256) ON public.model_versions TO {role}')
            db.exec_driver_sql(f'GRANT SELECT (id,model_version_id,manifest_sha256,signer_key_sha256,expires_at) ON public.model_verifications TO {role}')
        reader = create_engine(owner.url.set(username=role, password=password), hide_parameters=True)
        with Session(owner, expire_on_commit=False) as db, db.begin():
            org = Organization(name='Rollback rehearsal')
            model = model_version()
            user = User(email=f'{uuid4().hex}@example.com',
                        password_hash=PasswordHasher().hash('synthetic-rollback'))
            db.add_all([org, model, user])
            db.flush()
            camera = seed_camera(db, org.id)
            db.get(Camera, camera).model_revision = 1
            seed_verified_model(db, model)
            db.add_all([
                CameraModelAssignment(camera_id=camera, model_version_id=model.id),
                CameraModelHistory(camera_id=camera, revision=1, organization_id=org.id,
                                   actor_user_id=user.id, model_version_id=model.id),
                AuditLog(organization_id=org.id, actor_user_id=user.id, action='camera.model_assign',
                         target_type='camera', target_id=camera),
                OrganizationMembership(organization_id=org.id, user_id=user.id, role='admin'),
            ])
        query = {'model_key': model.model_key, 'model_version': model.version, 'nonce': str(uuid4())}
        with TestClient(create_authority(AUTHORITY, postgres_resolver(reader, 5))) as server:
            response = server.post(LEASE_PATH, json=query, headers=LEASE_AUTH)
            assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
            lease = ModelLease.model_validate(response.json())
            assert str(lease.nonce) == query['nonce'] and lease.id == model.id
            with reader.connect() as db, pytest.raises(DBAPIError):
                db.execute(text('UPDATE public.model_versions SET version=version WHERE id=:id'), {'id': model.id})
            with Session(owner) as db, db.begin():
                db.add(ModelVerificationRevocation(verification_id=lease.verification_id,
                                                   actor='test', revoked_at=utcnow()))
            assert server.post(LEASE_PATH, json=query, headers=LEASE_AUTH).status_code == 404

        # Shut down the opt-in authority and return to the unchanged business API.
        def business_db():
            with Session(owner) as db:
                yield db

        business_app.dependency_overrides[get_db] = business_db
        try:
            with TestClient(business_app) as app:
                assert app.post(LEASE_PATH, json=query, headers=LEASE_AUTH).status_code == 404
                assert app.post(INFERENCE_PATH, json={}).status_code == 404
                login = app.post('/api/v1/auth/login', json={'email': user.email, 'password': 'synthetic-rollback'})
                assert login.status_code == 200
                current = app.get(f'/api/v1/organizations/{org.id}/cameras/{camera}/model', headers={
                    'Authorization': f"Bearer {login.json()['access_token']}",
                })
                assert current.status_code == 200 and current.json()['model_version']['id'] == model.id
                assert current.json()['revision'] == 1
        finally:
            business_app.dependency_overrides.pop(get_db)
        with owner.connect() as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'e5c19a74d620'
            assert db.scalar(select(CameraModelAssignment.model_version_id).where(
                CameraModelAssignment.camera_id == camera,
            )) == model.id
            assert db.scalar(select(CameraModelHistory.revision).where(
                CameraModelHistory.camera_id == camera,
            )) == 1
            assert db.scalar(select(AuditLog.action).where(AuditLog.target_id == camera)) == 'camera.model_assign'
            assert db.scalar(select(ModelVerificationRevocation.verification_id).where(
                ModelVerificationRevocation.verification_id == lease.verification_id,
            )) == lease.verification_id
    finally:
        if reader:
            reader.dispose()
        owner.dispose()
