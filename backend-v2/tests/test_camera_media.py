from uuid import uuid4

import pytest

from app.api import camera_media
from app.config import get_settings
from app.db.models import Camera, Organization, Site
from app.db.session import SessionLocal


@pytest.fixture
def access(admin_account, client):
    organization = admin_account['org_id']
    login = client.post('/api/v1/auth/login', json={key: admin_account[key] for key in ('email', 'password')})
    assert login.status_code == 200
    with SessionLocal.begin() as db:
        foreign = Organization(name='Other organization')
        db.add(foreign)
        db.flush()
        sites = [Site(name='Test site', organization_id=org) for org in (organization, foreign.id)]
        db.add_all(sites)
        db.flush()
        cameras = [Camera(name='Fixture', site_id=site.id, stream_ref='stream:media/test') for site in sites]
        db.add_all(cameras)
        db.flush()
        own, other = [camera.id for camera in cameras]
        foreign_id = foreign.id
    return organization, foreign_id, own, other, {'Authorization': 'Bearer ' + login.json()['access_token']}


def test_media_authorization_and_disabled_behavior(client, access, monkeypatch):
    organization, foreign, own, other, headers = access

    async def gateway(*args):
        pytest.fail('Unauthorized or disabled camera reached the media gateway')

    monkeypatch.setattr(camera_media, 'gateway_read', gateway)
    monkeypatch.setattr(get_settings(), 'media_gateway_origin', 'http://127.0.0.1:9081')
    for endpoint in ('status', 'preview'):
        url = f'/api/v1/organizations/{organization}/cameras/{own}/media/{endpoint}'
        assert client.get(url).status_code == 401
        for org, camera in ((foreign, other), (organization, other), (organization, uuid4())):
            denied = f'/api/v1/organizations/{org}/cameras/{camera}/media/{endpoint}'
            assert client.get(denied, headers=headers).status_code == 404
    with SessionLocal.begin() as db:
        db.get(Camera, own).enabled = False
    prefix = f'/api/v1/organizations/{organization}/cameras/{own}/media'
    assert client.get(f'{prefix}/status', headers=headers).json()['state'] == 'disabled'
    assert client.get(f'{prefix}/preview', headers=headers).status_code == 503


def test_media_uses_database_binding_and_returns_safe_response(client, access, monkeypatch):
    organization, _, own, _, headers = access
    prefix = f'/api/v1/organizations/{organization}/cameras/{own}/media'
    assert client.get(f'{prefix}/status', headers=headers).json()['state'] == 'not_monitored'
    assert client.get(f'{prefix}/preview', headers=headers).status_code == 503
    monkeypatch.setattr(get_settings(), 'media_gateway_origin', 'https://example.invalid:8080')
    assert client.get(f'{prefix}/preview', headers=headers).status_code == 503
    monkeypatch.setattr(get_settings(), 'media_gateway_origin', 'http://127.0.0.1:9081')

    async def gateway(camera, resource, _mime, _limit):
        assert camera.id == own and camera.stream_ref == 'stream:media/test'
        if resource == 'preview':
            return b'\x00\x00\x00\x18ftypisom'
        return b'{"state":"online","preview_available":true,"secret":"discarded"}'

    monkeypatch.setattr(camera_media, 'gateway_read', gateway)
    status = client.get(f'{prefix}/status', headers=headers, params={'stream_ref': 'stream:other'})
    assert status.json() == {'state': 'online', 'preview_available': True}
    response = client.get(f'{prefix}/preview', headers=headers)
    assert response.status_code == 200 and response.headers['content-type'] == 'video/mp4'
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 204
    assert client.get(f'{prefix}/preview', headers=headers).status_code == 401
