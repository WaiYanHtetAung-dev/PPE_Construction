import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import platform_models
from app.db.models import ModelVersion, PlatformAuditLog, PlatformPublisher, User
from app.db.session import SessionLocal
from app.scripts.platform_publishers import change_grant

PATH = '/api/v1/platform/model-versions'
BODY = {
    'model_key': 'ppe',
    'version': '1.0.0',
    'artifact_ref': 'approved/ppe/model.bin',
    'artifact_sha256': 'a' * 64,
    'class_map': {'worker': 'person', 'hard hat': 'helmet'},
}


@pytest.fixture(autouse=True)
def approved_namespace(monkeypatch):
    monkeypatch.setattr(platform_models, 'get_settings', lambda: SimpleNamespace(model_artifact_namespace='approved'))


@pytest.fixture
def headers(client, admin_account):
    response = client.post('/api/v1/auth/login', json={
        'email': admin_account['email'], 'password': admin_account['password'],
    })
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


@pytest.fixture
def publisher(headers, admin_account):
    with SessionLocal.begin() as db:
        db.add(PlatformPublisher(user_id=admin_account['user_id']))
    return headers


def test_registration_and_duplicate(client, publisher, admin_account):
    created = client.post(PATH, headers=publisher, json=BODY)
    assert created.status_code == 201
    assert created.json()['inference_eligible'] is False
    assert 'artifact_ref' not in created.json()
    changed = dict(BODY, artifact_sha256='b' * 64)
    assert client.post(PATH, headers=publisher, json=changed).status_code == 409
    assert client.patch(f"{PATH}/{created.json()['id']}", headers=publisher, json=changed).status_code == 404
    with SessionLocal() as db:
        model = db.scalars(select(ModelVersion)).one()
        audit = db.scalars(select(PlatformAuditLog)).one()
        assert model.artifact_sha256 == BODY['artifact_sha256']
        assert audit.actor == admin_account['user_id']
        assert audit.target_id == model.id
        assert audit.action == 'model_version.register'


def test_requires_platform_grant(client, headers):
    assert client.post(PATH, json=BODY).status_code == 401
    assert client.post(PATH, headers=headers, json=BODY).status_code == 403


@pytest.mark.parametrize('field,value', [
    ('model_key', 'bad/key'), ('version', '../v1'),
    ('artifact_sha256', 'invalid'), ('class_map', {'worker': 'unknown'}),
    ('artifact_ref', 'https://user:secret@host/file'),
    ('artifact_ref', 'rtsp://host/file'), ('artifact_ref', 'C:/local/file'),
    ('artifact_ref', '/approved/file'), ('artifact_ref', 'approved/../file'),
    ('artifact_ref', 'approved/%2e%2e/file'), ('artifact_ref', 'other/file'),
])
def test_invalid_metadata(client, publisher, field, value):
    response = client.post(PATH, headers=publisher, json=dict(BODY, **{field: value}))
    assert response.status_code == 422
    assert 'secret' not in response.text
    with SessionLocal() as db:
        assert db.scalar(select(ModelVersion)) is None
        assert db.scalar(select(PlatformAuditLog)) is None


def test_audit_failure_rolls_back_registry(client, publisher):
    def fail_audit(*args):
        raise RuntimeError('audit failure')

    event.listen(PlatformAuditLog, 'before_insert', fail_audit)
    try:
        response = client.post(PATH, headers=publisher, json=BODY)
    finally:
        event.remove(PlatformAuditLog, 'before_insert', fail_audit)
    assert response.status_code == 500
    with SessionLocal() as db:
        assert db.scalar(select(ModelVersion)) is None


def test_grant_and_revoke_are_audited_and_idempotent(admin_account):
    user_id = admin_account['user_id']
    with SessionLocal.begin() as db:
        assert change_grant(db, user_id, True, 'postgres:operator')
        assert not change_grant(db, user_id, True, 'postgres:operator')
        db.get(User, user_id).is_active = False
        db.flush()
        assert change_grant(db, user_id, False, 'postgres:operator')
        assert not change_grant(db, user_id, False, 'postgres:operator')
        with pytest.raises(ValueError):
            change_grant(db, user_id, True, 'postgres:operator')
        with pytest.raises(ValueError):
            change_grant(db, 'unknown', True, 'postgres:operator')
        assert sorted(db.scalars(select(PlatformAuditLog.action))) == ['publisher.grant', 'publisher.revoke']


def test_postgres_duplicate_race_and_immutable_metadata():
    url = os.environ.get('PPE_DISPOSABLE_POSTGRES_URL')
    if not url:
        pytest.skip('Set PPE_DISPOSABLE_POSTGRES_URL to a migrated disposable test database')
    engine = create_engine(url)
    assert engine.dialect.name == 'postgresql'
    user_id = str(uuid4())
    model_key = 'test-' + user_id
    body = platform_models.ModelRegistration(**dict(BODY, model_key=model_key))
    start = Barrier(2)

    def register():
        with Session(engine) as db:
            user = db.get(User, user_id)
            start.wait(timeout=15)
            try:
                platform_models.register_model(body, user, db)
            except HTTPException as error:
                return error.status_code
            return 201

    try:
        with Session(engine) as db, db.begin():
            db.add(User(id=user_id, email=f'{user_id}@example.invalid', password_hash='unused'))
            db.flush()
            db.add(PlatformPublisher(user_id=user_id))
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert sorted(workers.map(lambda _: register(), range(2))) == [201, 409]
        with Session(engine) as db:
            model = db.scalars(select(ModelVersion).where(ModelVersion.model_key == model_key)).one()
            audit = db.scalars(select(PlatformAuditLog).where(PlatformAuditLog.target_id == model.id)).one()
            assert audit.actor == user_id
            with pytest.raises(IntegrityError):
                db.execute(update(ModelVersion).where(ModelVersion.id == model.id).values(artifact_sha256='f' * 64))
            db.rollback()
    finally:
        engine.dispose()
