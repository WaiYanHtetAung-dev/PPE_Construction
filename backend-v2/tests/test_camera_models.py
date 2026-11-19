import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.camera_models import AssignmentInput, put_assignment
from app.db.models import (
    AuditLog, Camera, CameraModelAssignment, CameraModelHistory, ModelVersion, Organization,
    OrganizationMembership, Site, User,
)
from app.db.session import SessionLocal


def seed_camera(db, org_id):
    site = Site(organization_id=org_id, name='Site')
    db.add(site)
    db.flush()
    camera = Camera(site_id=site.id, name='Gate', stream_ref='stream:test/gate')
    db.add(camera)
    db.flush()
    return camera.id


def seed_models(db):
    key = 'ppe-' + uuid4().hex
    versions = [
        ModelVersion(model_key=key, version=str(n), artifact_ref='private/model.bin',
                     artifact_sha256='a' * 64, inference_eligible=n < 3)
        for n in range(1, 4)
    ]
    db.add_all(versions)
    db.flush()
    return [version.id for version in versions]


@pytest.fixture
def assignment(client, admin_account):
    login = client.post('/api/v1/auth/login', json={
        'email': admin_account['email'], 'password': admin_account['password'],
    })
    headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
    org_id = admin_account['org_id']
    with SessionLocal.begin() as db:
        foreign_org = Organization(name='Other')
        db.add(foreign_org)
        db.flush()
        foreign = seed_camera(db, foreign_org.id)
        camera = seed_camera(db, org_id)
        models = seed_models(db)
    prefix = f'/api/v1/organizations/{org_id}/cameras'
    return headers, f'{prefix}/{camera}/model', f'{prefix}/{foreign}/model', models


def put(client, path, headers, model, revision):
    return client.put(path, headers=headers, json={
        'model_version_id': model, 'expected_revision': revision,
    })


def test_assignment_switch_rollback_unassign_and_history(client, assignment):
    headers, path, _, (first, second, _) = assignment
    assert client.get(path, headers=headers).json() == {'revision': 0, 'model_version': None}
    for revision, model in enumerate((first, second, first, None, second)):
        result = put(client, path, headers, model, revision)
        assert result.status_code == 200
        assert result.json()['revision'] == revision + 1
        if model is None:
            assert result.json()['model_version'] is None
        else:
            assert result.json()['model_version']['id'] == model
        assert client.get(path, headers=headers).json() == result.json()
    assert put(client, path, headers, second, 5).json()['revision'] == 5
    assert put(client, path, headers, second, 4).status_code == 409
    history = client.get(path + '/history', headers=headers).json()
    assert [entry['revision'] for entry in history] == [5, 4, 3, 2, 1]
    assert history[2]['model_version_id'] == first
    assert history[2]['previous_model_version_id'] == second
    assert client.get(path + '/history?before_revision=3&limit=1', headers=headers).json()[0]['revision'] == 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 5


def test_assignment_access_and_validation(client, assignment, admin_account):
    headers, path, foreign_path, (first, _, ineligible) = assignment
    assert client.get(path).status_code == 401
    assert put(client, path, {}, first, 0).status_code == 401
    assert client.get(path + '/history').status_code == 401
    assert put(client, foreign_path, headers, first, 0).status_code == 404
    assert client.get(foreign_path, headers=headers).status_code == 404
    assert client.get(foreign_path + '/history', headers=headers).status_code == 404
    assert put(client, path, headers, ineligible, 0).status_code == 404
    assert put(client, path, headers, str(uuid4()), 0).status_code == 404
    assert put(client, path, headers, first, -1).status_code == 422
    with SessionLocal.begin() as db:
        membership = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.user_id == admin_account['user_id'],
        ))
        membership.role = 'viewer'
    assert put(client, path, headers, first, 0).status_code == 404
    assert client.get(path, headers=headers).status_code == 404
    assert client.get(path + '/history', headers=headers).status_code == 404


def test_assignment_rolls_back_on_audit_failure(client, assignment):
    headers, path, _, (first, _, _) = assignment

    def fail_audit(*args):
        raise RuntimeError('injected audit failure')

    event.listen(AuditLog, 'before_insert', fail_audit)
    try:
        assert put(client, path, headers, first, 0).status_code == 500
    finally:
        event.remove(AuditLog, 'before_insert', fail_audit)
    assert client.get(path, headers=headers).json() == {'revision': 0, 'model_version': None}
    assert client.get(path + '/history', headers=headers).json() == []


def test_postgres_concurrent_assignments_and_append_only_history():
    url = os.environ.get('PPE_DISPOSABLE_POSTGRES_URL')
    if not url:
        pytest.skip('Set PPE_DISPOSABLE_POSTGRES_URL to a migrated disposable test database')
    engine = create_engine(url)
    assert engine.dialect.name == 'postgresql'
    try:
        with Session(engine) as db, db.begin():
            org = Organization(name='Assignment test')
            users = [User(email=f'{uuid4()}@example.invalid', password_hash='unused') for _ in range(2)]
            db.add_all([org, *users])
            db.flush()
            org_id = org.id
            user_ids = [user.id for user in users]
            db.add_all([OrganizationMembership(organization_id=org_id, user_id=user_id, role='admin')
                        for user_id in user_ids])
            camera = seed_camera(db, org_id)
            first, second, _ = seed_models(db)

        def compete(revision):
            gate = Barrier(2)

            def assign(user_id, model_id):
                with Session(engine) as db:
                    user = db.get(User, user_id)
                    gate.wait(timeout=15)
                    try:
                        result = put_assignment(org_id, UUID(camera), AssignmentInput(
                            expected_revision=revision, model_version_id=UUID(model_id),
                        ), user, db)
                        return 200, result.model_version.id
                    except HTTPException as error:
                        return error.status_code, None

            with ThreadPoolExecutor(max_workers=2) as workers:
                outcomes = list(workers.map(assign, user_ids, (first, second)))
            assert sorted(status for status, _ in outcomes) == [200, 409]
            return next(model for status, model in outcomes if status == 200)

        winner = compete(0)
        # Remove the previous winner from the candidates so both updates mutate the selection.
        with Session(engine) as db, db.begin():
            alternative, _, _ = seed_models(db)
        if winner == first:
            first = alternative
        else:
            second = alternative
        final = compete(1)
        with Session(engine) as db:
            assert db.get(Camera, camera).model_revision == 2
            assert db.get(CameraModelAssignment, camera).model_version_id == final
            history = db.scalars(select(CameraModelHistory).where(
                CameraModelHistory.camera_id == camera,
            ).order_by(CameraModelHistory.revision)).all()
            assert [entry.model_version_id for entry in history] == [winner, final]
            assert history[1].previous_model_version_id == winner
            assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.target_id == camera)) == 2
            with pytest.raises(IntegrityError):
                db.execute(update(CameraModelHistory).where(
                    CameraModelHistory.camera_id == camera,
                ).values(model_version_id=None))
            db.rollback()
    finally:
        engine.dispose()
