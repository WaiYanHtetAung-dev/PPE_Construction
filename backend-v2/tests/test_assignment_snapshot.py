import hashlib
import os
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.assignment_snapshot import create_app, postgres_reader
from app.contracts.assignment_snapshot import SNAPSHOT_PATH, parse_snapshot_response
from app.db.models import (
    Camera, CameraModelAssignment, ModelVerificationRevocation, Organization, Site,
)
from app.scripts.gateway_credentials import provision, revoke, rotate
from tests.model_fixtures import seed_verified_model
from tests.test_model_verification import model_version


def query():
    return {'schema_version': '1.0', 'organization_id': str(uuid4()), 'site_id': str(uuid4()),
            'camera_id': str(uuid4()), 'nonce': str(uuid4())}


def test_private_route_auth_scope_validation_and_denial(client):
    request = query()
    key, secret = str(uuid4()), token_urlsafe(32)
    headers = {'Authorization': f'Bearer {key}.{secret}'}
    now = datetime.now(UTC)

    def read(identifier, ask):
        if identifier != key:
            return None
        return {'secret_sha256': hashlib.sha256(secret.encode()).hexdigest(), 'issued_at': now,
                'camera_id': request['camera_id'] if ask and str(ask.camera_id) == request['camera_id'] else None,
                'model_version_id': None, 'enabled': True, 'model_revision': 0,
                'verification_generation': None, 'revoked_through_generation': None}

    assert client.post(SNAPSHOT_PATH, headers=headers, json=request).status_code == 404
    with TestClient(create_app(read)) as private:
        assert private.post(SNAPSHOT_PATH, json=request).status_code == 401
        assert private.post(SNAPSHOT_PATH, json=request, headers={'Authorization': f'Bearer {key}.{token_urlsafe(32)}'}).status_code == 401
        assert private.post(SNAPSHOT_PATH, headers=headers, json=request | {'camera_id': str(uuid4())}).status_code == 404
        assert private.post(SNAPSHOT_PATH, headers=headers, json=request | {'schema_version': '2.0'}).status_code == 422
        assert private.post(SNAPSHOT_PATH, headers=headers, content=b'{"a":1,"a":2}').status_code == 422
        assert private.post(SNAPSHOT_PATH, headers=headers, content=b' ' * 2049).status_code == 413
        response = private.post(SNAPSHOT_PATH, headers=headers, json=request)
        assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
        snapshot = parse_snapshot_response(response.content)
        assert snapshot.decision == 'unassigned' and str(snapshot.nonce) == request['nonce']


def test_postgres_snapshot_scope_rotation_and_evidence_ordering():
    url = os.environ.get('PPE_DISPOSABLE_POSTGRES_URL')
    if not url:
        pytest.skip('Requires migrated disposable PostgreSQL')
    owner = create_engine(url, hide_parameters=True)
    assert owner.dialect.name == 'postgresql'
    reader = None
    role, password = 'snapshot_' + uuid4().hex, uuid4().hex
    try:
        with owner.begin() as db:
            if db.scalar(text("SELECT to_regrole('ppe_assignment_operator')")) is None:
                db.execute(text('CREATE ROLE ppe_assignment_operator NOLOGIN'))
            db.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
            db.exec_driver_sql(f'GRANT SELECT ON public.gateway_snapshot_credentials, public.gateway_snapshot_assignments TO {role}')
        reader = create_engine(owner.url.set(username=role, password=password), hide_parameters=True)
        with Session(owner, expire_on_commit=False) as db, db.begin():
            org, model_a, model_b = Organization(name='Synthetic Snapshot'), model_version(), model_version()
            model_a.class_map = model_b.class_map = {'person': 'person'}
            db.add_all([org, model_a, model_b])
            db.flush()
            site = Site(organization_id=org.id, name='Synthetic Site')
            db.add(site)
            db.flush()
            camera = Camera(site_id=site.id, name='Camera', stream_ref='stream:test/snapshot')
            db.add(camera)
            db.flush()
            for model in (model_a, model_b):
                seed_verified_model(db, model)
            db.add(CameraModelAssignment(camera_id=camera.id, model_version_id=model_a.id))
            principal = provision(db, org.id, {camera.id: site.id})
            old = rotate(db, principal)

        request = query() | {'organization_id': org.id, 'site_id': site.id, 'camera_id': camera.id}
        with TestClient(create_app(postgres_reader(reader))) as listener:
            def send(token=old, **changes):
                return listener.post(SNAPSHOT_PATH, json=request | changes,
                                     headers={'Authorization': f'Bearer {token}'})

            first = parse_snapshot_response(send().content)
            assert first.decision == 'eligible' and str(first.model.model_version_id) == model_a.id
            assert first.expires_at - first.issued_at <= timedelta(seconds=10)
            for field in ('organization_id', 'site_id', 'camera_id'):
                assert send(**{field: str(uuid4())}).status_code == 404
            with reader.begin() as db, pytest.raises(DBAPIError):
                db.execute(text('UPDATE public.gateway_principals SET disabled_at = now()'))

            with Session(owner) as db, db.begin():
                db.add(ModelVerificationRevocation(verification_id=first.verification_generation,
                                                   actor='synthetic-test', revoked_at=datetime.now(UTC)))
                db.flush()
                assert parse_snapshot_response(send().content).decision == 'eligible'
            denied = parse_snapshot_response(send().content)
            assert denied.decision == 'revoked' and denied.assignment_revision == first.assignment_revision
            with Session(owner) as db, db.begin():
                seed_verified_model(db, model_a)
            renewed = parse_snapshot_response(send().content)
            assert renewed.decision == 'eligible' and renewed.verification_generation > denied.verification_generation
            assert renewed.revoked_through_generation == denied.verification_generation
            with Session(owner) as db, db.begin():
                db.get(Camera, camera.id).model_revision += 1
                db.get(CameraModelAssignment, camera.id).model_version_id = model_b.id
                db.flush()
                assert parse_snapshot_response(send().content).model == first.model
            switched = parse_snapshot_response(send().content)
            assert str(switched.model.model_version_id) == model_b.id
            assert switched.assignment_revision == first.assignment_revision + 1
            with Session(owner) as db, db.begin():
                new = rotate(db, principal)
            assert send().status_code == send(new).status_code == 200
            with Session(owner) as db, db.begin():
                revoke(db, principal, old.split('.')[0])
            assert send().status_code == 401 and send(new).status_code == 200
            with Session(owner) as db, db.begin():
                revoke(db, principal)
            assert send(new).status_code == 401
    finally:
        if reader is not None:
            reader.dispose()
        owner.dispose()
