import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Camera, Incident, IncidentOutbox, Organization, OrganizationMembership, Site, utcnow
from app.db.session import SessionLocal, get_db
from app.incident_ingestion import create_ingestion
from app.scripts import incident_outbox

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


def test_outbox_retry_retains_event_identity_and_marks_success(monkeypatch):
    with SessionLocal.begin() as db:
        payload = seed(db)
    with TestClient(create_ingestion(SECRET)) as internal:
        created = internal.post(PATH, json=payload, headers=HEADERS)
        assert created.status_code == 201

    now = utcnow()
    monkeypatch.setattr(incident_outbox, 'utcnow', lambda: now)
    sent = []

    def publish(event):
        sent.append(event)
        return len(sent) > 1

    with SessionLocal() as db:
        assert incident_outbox.deliver_one(db, publish) is incident_outbox.DeliveryResult.RETRY_SCHEDULED
        assert incident_outbox.deliver_one(db, publish) is incident_outbox.DeliveryResult.EMPTY
    now += timedelta(seconds=3)
    with SessionLocal() as db:
        assert incident_outbox.deliver_one(db, publish) is incident_outbox.DeliveryResult.PUBLISHED
        assert incident_outbox.deliver_one(db, publish) is incident_outbox.DeliveryResult.EMPTY
        row = db.get(IncidentOutbox, payload['event_id'])
        assert row.attempts == 2 and row.retry_at is None and row.published_at is not None
    assert sent == [incident_outbox.IncidentCreated(
        payload['event_id'], payload['organization_id'], created.json()['incident_id'],
    )] * 2


def test_incident_status_transitions_require_org_admin_and_audit(client, admin_account):
    with SessionLocal.begin() as db:
        payload = seed(db)
        membership = OrganizationMembership(user_id=admin_account['user_id'],
                                            organization_id=payload['organization_id'], role='viewer')
        db.add(membership)
        db.flush()
        membership_id = membership.id
    with TestClient(create_ingestion(SECRET)) as internal:
        created = internal.post(PATH, json=payload, headers=HEADERS)
    assert created.status_code == 201
    incident_id = created.json()['incident_id']
    login = client.post('/api/v1/auth/login', json={
        'email': admin_account['email'], 'password': admin_account['password'],
    })
    headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
    prefix = '/api/v1/organizations'
    url = f"{prefix}/{payload['organization_id']}/incidents/{incident_id}/status"
    acknowledge = {'status': 'acknowledged'}
    resolve = {'status': 'resolved'}
    assert client.patch(url, json=acknowledge).status_code == 401
    assert client.patch(url, json=acknowledge, headers=headers).status_code == 404
    wrong_org = f"{prefix}/{admin_account['org_id']}/incidents/{incident_id}/status"
    assert client.patch(wrong_org, json=acknowledge, headers=headers).status_code == 404
    with SessionLocal.begin() as db:
        db.get(OrganizationMembership, membership_id).role = 'admin'
    assert client.patch(url, json=resolve, headers=headers).status_code == 409
    assert client.patch(url, json=acknowledge, headers=headers).json()['status'] == 'acknowledged'
    assert client.patch(url, json=resolve, headers=headers).json()['status'] == 'resolved'
    assert client.patch(url, json=acknowledge, headers=headers).status_code == 409
    with SessionLocal() as db:
        log = db.scalars(select(AuditLog).where(AuditLog.target_id == incident_id)).all()
        assert {entry.action for entry in log} == {'incident.acknowledged', 'incident.resolved'}
        assert all(entry.actor_user_id == admin_account['user_id'] for entry in log)


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

        publishing = Event()
        release = Event()

        def slow_publish(message):
            assert message.event_id == payload['event_id']
            publishing.set()
            assert release.wait(timeout=10)
            return True

        def deliver():
            with Session(engine) as db:
                return incident_outbox.deliver_one(db, slow_publish)

        with ThreadPoolExecutor(max_workers=1) as pool:
            delivery = pool.submit(deliver)
            try:
                assert publishing.wait(timeout=10)
                with Session(engine) as db:
                    assert incident_outbox.deliver_one(db, lambda _: pytest.fail('Duplicate dispatch')) is (
                        incident_outbox.DeliveryResult.EMPTY
                    )
            finally:
                release.set()
            assert delivery.result(timeout=10) is incident_outbox.DeliveryResult.PUBLISHED
    finally:
        engine.dispose()
