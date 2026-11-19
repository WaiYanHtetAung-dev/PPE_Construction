from argon2 import PasswordHasher
from sqlalchemy import select

from app.db.models import Organization, OrganizationMembership, User
from app.db.session import SessionLocal


def login(client, email='admin@ppe.example', password='strong-test-password'):
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': f'Bearer {response.json()["access_token"]}'}


def test_health(client):
    assert client.get('/health/live').json() == {'status': 'ok'}
    assert client.get('/health/ready').json() == {'status': 'ready'}


def test_auth_required(client, admin_account):
    response = client.get(f'/api/v1/organizations/{admin_account["org_id"]}/sites')
    assert response.status_code == 401


def test_invalid_login(client, admin_account):
    r = client.post('/api/v1/auth/login', json={'email': admin_account['email'], 'password': 'wrong'})
    assert r.status_code == 401


def test_site_camera_flow_and_logout(client, admin_account):
    headers = login(client)
    me = client.get('/api/v1/auth/me', headers=headers)
    assert me.status_code == 200
    org_id = me.json()['memberships'][0]['organization_id']
    assert org_id == admin_account['org_id']
    r = client.post(f'/api/v1/organizations/{org_id}/sites', json={'name': 'Site A'}, headers=headers)
    assert r.status_code == 201, r.text
    site_id = r.json()['id']
    r = client.post(f'/api/v1/organizations/{org_id}/sites/{site_id}/cameras',
                    json={'name': 'Camera 1', 'stream_ref': 'stream:site-a/cam-1'}, headers=headers)
    assert r.status_code == 201, r.text
    assert 'rtsp_url' not in r.json()
    r = client.get(f'/api/v1/organizations/{org_id}/sites/{site_id}/cameras', headers=headers)
    assert r.status_code == 200 and len(r.json()) == 1
    r = client.get(f'/api/v1/organizations/{org_id}/incidents', headers=headers)
    assert r.status_code == 200 and r.json()['total'] == 0
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 204
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401


def test_cross_tenant_deny(client, admin_account):
    headers = login(client)
    with SessionLocal.begin() as db:
        other = Organization(name='Other company')
        db.add(other)
        db.flush()
        other_id = other.id
    assert client.get(f'/api/v1/organizations/{other_id}/sites', headers=headers).status_code == 404
    assert client.post(f'/api/v1/organizations/{other_id}/sites', json={'name':'Sneak'}, headers=headers).status_code == 404
    assert client.get(f'/api/v1/organizations/{other_id}/incidents', headers=headers).status_code == 404


def test_viewer_cannot_mutate(client, admin_account):
    with SessionLocal.begin() as db:
        viewer = User(email='viewer@ppe.example', password_hash=PasswordHasher().hash('viewer-test-password'))
        db.add(viewer)
        db.flush()
        db.add(OrganizationMembership(user_id=viewer.id, organization_id=admin_account['org_id'], role='viewer'))
    headers = login(client, 'viewer@ppe.example', 'viewer-test-password')
    url = f'/api/v1/organizations/{admin_account["org_id"]}/sites'
    assert client.get(url, headers=headers).status_code == 200
    assert client.post(url, json={'name': 'Not allowed'}, headers=headers).status_code == 404


def test_no_rtsp_urls_allowed_in_camera_input(client, admin_account):
    headers = login(client)
    org_id = admin_account['org_id']
    site_id = client.post(f'/api/v1/organizations/{org_id}/sites', json={'name': 'Site B'}, headers=headers).json()['id']
    r = client.post(f'/api/v1/organizations/{org_id}/sites/{site_id}/cameras',
                    json={'name': 'Camera', 'stream_ref': 'rtsp://admin:password@192.168.1.5/live'}, headers=headers)
    assert r.status_code == 422


def test_stream_ref_path_traversal_rejected(client, admin_account):
    headers = login(client)
    org_id = admin_account['org_id']
    site_id = client.post(f'/api/v1/organizations/{org_id}/sites', json={'name': 'Site C'}, headers=headers).json()['id']
    r = client.post(f'/api/v1/organizations/{org_id}/sites/{site_id}/cameras',
                    json={'name': 'Camera', 'stream_ref': 'stream:../../secrets'}, headers=headers)
    assert r.status_code == 422
