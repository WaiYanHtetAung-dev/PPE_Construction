import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.db.models import Camera, Incident, IncidentOutbox, Organization, Site, utcnow
from app.db.session import SessionLocal, get_db
from app.incident_ingestion import create_ingestion

PATH = '/internal/v1/incidents'
SECRET = 'synthetic-ingestion-credential-for-tests'
HEADERS = {'Authorization': f'Bearer {SECRET}'}


def seed(session):
    org = Organization(name='Ingestion Test Organization')
    session.add(org)
    session.flush()
    site = Site(organization_id=org.id, name='Ingestion Test Site')
    session.add(site)
    session.flush()
    camera = Camera(site_id=site.id, name='Ingestion Test Camera', stream_ref='stream:ingestion-ci')
    session.add(camera)
    session.flush()
    return {'event_id': str(uuid4()), 'organization_id': org.id, 'site_id': site.id,
            'camera_id': camera.id, 'detected_at': utcnow().isoformat(), 'violation_type': 'missing_helmet'}


def test_private_ingest_auth_binding_and_idempotency(client):
    with SessionLocal.begin() as db:
        payload = seed(db)
    assert client.post(PATH, json=payload, headers=HEADERS).status_code == 404

    with TestClient(create_ingestion(SECRET)) as internal:
        assert internal.post(PATH, json=payload).status_code == 401
        invalid = payload | {'organization_id': str(uuid4())}
        assert internal.post(PATH, json=invalid, headers=HEADERS).status_code == 404
        assert internal.post(PATH, json=payload | {'credential': 'synthetic'}, headers=HEADERS).json() == {
            'detail': 'Invalid internal request',
        }
        created = internal.post(PATH, json=payload, headers=HEADERS)
        replayed = internal.post(PATH, json=payload, headers=HEADERS)
        assert (created.status_code, replayed.status_code) == (201, 200)
        assert created.json() == replayed.json()
        assert internal.post(PATH, json=payload | {'violation_type': 'missing_vest'},
                             headers=HEADERS).status_code == 409

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == 1
        outbox = db.get(IncidentOutbox, payload['event_id'])
        assert outbox.incident_id == created.json()['incident_id']
        assert outbox.published_at is None


def test_outbox_failure_rolls_back_incident():
    with SessionLocal.begin() as db:
        payload = seed(db)
    app = create_ingestion(SECRET)

    def db_with_failure():
        with SessionLocal() as db:
            @event.listens_for(db, 'before_flush')
            def fail_outbox(session, *_):
                if any(isinstance(row, IncidentOutbox) for row in session.new):
                    raise RuntimeError('Synthetic outbox fault')

            yield db

    app.dependency_overrides[get_db] = db_with_failure
    with TestClient(app, raise_server_exceptions=False) as internal:
        assert internal.post(PATH, json=payload, headers=HEADERS).status_code == 500
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Incident)) == 0
            assert db.get(IncidentOutbox, payload['event_id']) is None
        app.dependency_overrides.clear()
        assert internal.post(PATH, json=payload, headers=HEADERS).status_code == 201


def test_postgres_concurrent_duplicate_delivery():
    url = os.environ.get('PPE_DISPOSABLE_POSTGRES_URL')
    if not url:
        pytest.skip('Set PPE_DISPOSABLE_POSTGRES_URL to a migrated disposable test database')
    engine = create_engine(url)
    assert engine.dialect.name == 'postgresql'
    gate = Barrier(2)
    app = create_ingestion(SECRET)

    def concurrent_db():
        with Session(engine) as db:
            @event.listens_for(db, 'before_flush')
            def pause_before_outbox(session, *_):
                if any(isinstance(row, IncidentOutbox) for row in session.new):
                    gate.wait(timeout=10)

            yield db

    app.dependency_overrides[get_db] = concurrent_db
    try:
        with Session(engine) as db, db.begin():
            payload = seed(db)

        def submit(_):
            with TestClient(app) as internal:
                return internal.post(PATH, json=payload, headers=HEADERS)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(submit, range(2))
        assert sorted([first.status_code, second.status_code]) == [200, 201]
        assert first.json() == second.json()
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Incident).where(
                Incident.camera_id == payload['camera_id'],
            )) == 1
            assert db.get(IncidentOutbox, payload['event_id']).incident_id == first.json()['incident_id']
    finally:
        engine.dispose()
