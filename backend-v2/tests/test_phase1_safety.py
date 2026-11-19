"""Phase 1 added regression tests. Test DB is synthetic and reset by conftest."""
from datetime import timedelta

from sqlalchemy import select

from app.api.dependencies import now_utc
from app.db.models import Organization, SessionToken, Site, User
from app.db.session import SessionLocal
from tests.test_api import login


def test_duplicate_site_returns_conflict(client, admin_account):
    headers = login(client)
    path = f'/api/v1/organizations/{admin_account["org_id"]}/sites'
    body = {'name': 'Duplicate Site'}
    assert client.post(path, json=body, headers=headers).status_code == 201
    assert client.post(path, json=body, headers=headers).status_code == 409
    assert len(client.get(path, headers=headers).json()) == 1


def test_cross_org_site_id_cannot_add_camera(client, admin_account):
    headers = login(client)
    with SessionLocal.begin() as db:
        other_org = Organization(name='Org B')
        db.add(other_org)
        db.flush()
        other_site = Site(organization_id=other_org.id, name='Hidden B Site')
        db.add(other_site)
        db.flush()
        site_id = other_site.id
    path = f'/api/v1/organizations/{admin_account["org_id"]}/sites/{site_id}/cameras'
    response = client.post(path, headers=headers,
        json={'name': 'C', 'stream_ref': 'stream:site-b/camera'})
    assert response.status_code == 404
    assert client.get(path, headers=headers).status_code == 404


def test_disabled_user_cannot_use_active_token(client, admin_account):
    headers = login(client)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == admin_account['email']))
        user.is_active = False
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401


def test_expired_session_token_rejected(client, admin_account):
    headers = login(client)
    with SessionLocal.begin() as db:
        session = db.scalar(select(SessionToken))
        session.expires_at = now_utc() - timedelta(hours=1)
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401


def test_invalid_camera_aliases_are_rejected(client, admin_account):
    headers = login(client)
    org = admin_account['org_id']
    site_id = client.post(f'/api/v1/organizations/{org}/sites',
        headers=headers, json={'name': 'Valid'}).json()['id']
    route = f'/api/v1/organizations/{org}/sites/{site_id}/cameras'
    for alias in ['http://127.0.0.1/admin', 'rtsp://user:pass@10.1.1.2/stream', 'stream:../../passwd']:
        result = client.post(route, headers=headers, json={'name': 'Camera', 'stream_ref': alias})
        assert result.status_code == 422
