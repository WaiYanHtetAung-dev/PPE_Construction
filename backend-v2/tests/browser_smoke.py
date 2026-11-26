"""Opt-in browser smoke against the built frontend and isolated FastAPI test DB."""

import os
import socket
import subprocess
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from app.db.models import Camera, Incident, Organization, OrganizationMembership, Site
from app.db.session import SessionLocal
from app.main import app

FRONTEND = Path(__file__).resolve().parents[2] / 'frontend-v2'
ME = '/api/v1/auth/me'


@pytest.fixture
def smoke_origin(admin_account, tmp_path):
    org_id = admin_account['org_id']
    with SessionLocal.begin() as db:
        site = Site(organization_id=org_id, name='Smoke Test Site')
        db.add(site)
        db.flush()
        camera = Camera(site_id=site.id, name='Smoke Test Camera', stream_ref='stream:smoke-camera')
        db.add(camera)
        db.flush()
        db.add(Incident(organization_id=org_id, site_id=site.id, camera_id=camera.id,
                        violation_type='smoke-violation', detected_at=datetime.now(timezone.utc)))

    assert (FRONTEND / 'dist' / 'index.html').is_file(), 'Run pnpm run build first'
    port_file = tmp_path / 'vite-port'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        api_port = listener.getsockname()[1]
        api = uvicorn.Server(uvicorn.Config(app, workers=1, proxy_headers=False, log_level='warning'))
        thread = Thread(target=api.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not api.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    pytest.fail('Disposable FastAPI server failed to start')
                time.sleep(0.05)
            with subprocess.Popen(
                ['node', 'scripts/smoke-preview.mjs', str(port_file)], cwd=FRONTEND,
                env=os.environ | {'PPE_API_ORIGIN': f'http://127.0.0.1:{api_port}'},
            ) as preview:
                try:
                    deadline = time.monotonic() + 15
                    while True:
                        port = port_file.read_text().strip() if port_file.exists() else ''
                        if port.isdecimal() and int(port) > 0:
                            break
                        if preview.poll() is not None or time.monotonic() >= deadline:
                            pytest.fail('Vite preview failed to start')
                        time.sleep(0.05)
                    yield f'http://127.0.0.1:{port}'
                finally:
                    preview.terminate()
                    try:
                        preview.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        preview.kill()
        finally:
            api.should_exit = True
            thread.join(timeout=5)


def test_same_origin_session_and_data(smoke_origin, admin_account):
    prefix = f"/api/v1/organizations/{admin_account['org_id']}"
    responses = {}

    with sync_playwright() as playwright, closing(playwright.chromium.launch()) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', lambda route: (
            route.continue_() if route.request.url.startswith(f'{smoke_origin}/') else route.abort()
        ))
        page.on('response', lambda response: responses.update({response.url: response.status}))
        assert page.goto(smoke_origin).ok
        sign_in = page.get_by_role('heading', name='PPE V2 Sign In')
        expect(sign_in).to_be_visible()
        assert page.request.get(f'{smoke_origin}{ME}').status == 401
        assert page.request.get(f'{smoke_origin}{prefix}/sites').status == 401

        page.get_by_label('Email').fill(admin_account['email'])
        page.get_by_label('Password').fill('incorrect-smoke-password')
        page.get_by_role('button', name='Sign in').click()
        expect(page.get_by_role('alert')).to_have_text('Invalid email or password')
        assert responses[f'{smoke_origin}/api/v1/auth/login'] == 401

        page.get_by_label('Password').fill(admin_account['password'])
        with page.expect_response(f'{smoke_origin}/api/v1/auth/login') as login:
            page.get_by_role('button', name='Sign in').click()
        assert login.value.status == 200
        token = login.value.json()['access_token']

        expect(page.get_by_role('cell', name='Smoke Test Site').first).to_be_visible()
        expect(page.get_by_text('Smoke Test Camera', exact=True).first).to_be_visible()
        expect(page.get_by_text('smoke-violation', exact=True)).to_be_visible()
        assert responses[f'{smoke_origin}{ME}'] == 200
        assert responses[f'{smoke_origin}{prefix}/sites'] == 200
        assert responses[f'{smoke_origin}{prefix}/incidents?limit=100&offset=0'] == 200
        assert any(url.startswith(f'{smoke_origin}{prefix}/sites/') and url.endswith('/cameras')
                   and status == 200 for url, status in responses.items())

        sites_url = f'{smoke_origin}{prefix}/sites'
        page.route(sites_url, lambda route: route.fulfill(status=503, json={'detail': 'Unavailable'}))
        page.get_by_role('button', name='Refresh data').click()
        expect(page.get_by_role('alert')).to_have_text('Data request failed: HTTP 503')
        page.unroute(sites_url)
        with page.expect_response(sites_url) as refreshed:
            page.get_by_role('button', name='Refresh data').click()
        assert refreshed.value.status == 200
        expect(page.get_by_role('alert')).to_have_count(0)
        expect(page.get_by_role('button', name='Refresh data')).to_be_enabled()

        with page.expect_response(f'{smoke_origin}/api/v1/auth/logout') as logout:
            page.get_by_role('button', name='Sign out').click()
        assert logout.value.status == 204
        expect(sign_in).to_be_visible()
        assert page.request.get(f'{smoke_origin}{ME}', headers={
            'Authorization': f'Bearer {token}',
        }).status == 401


def test_switch_organization_and_handle_unauthorized(smoke_origin, admin_account):
    with SessionLocal.begin() as db:
        other = Organization(name='Other Smoke Organization')
        db.add(other)
        db.flush()
        other_id = other.id
        db.add(OrganizationMembership(user_id=admin_account['user_id'],
                                      organization_id=other_id, role='viewer'))

    with sync_playwright() as playwright, closing(playwright.chromium.launch()) as browser:
        page = browser.new_page()
        page.goto(smoke_origin)
        page.get_by_label('Email').fill(admin_account['email'])
        page.get_by_label('Password').fill(admin_account['password'])
        page.get_by_role('button', name='Sign in').click()
        organization = page.get_by_role('combobox', name='Organization')
        expect(organization).to_be_visible()
        if organization.input_value() != admin_account['org_id']:
            organization.select_option(admin_account['org_id'])
        camera = page.get_by_text('Smoke Test Camera', exact=True).first
        expect(camera).to_be_visible()

        other_sites = f'{smoke_origin}/api/v1/organizations/{other_id}/sites'
        with page.expect_response(other_sites) as switched:
            organization.select_option(other_id)
        assert switched.value.status == 200
        expect(camera).to_have_count(0)
        expect(page.get_by_text('smoke-violation', exact=True)).to_have_count(0)

        page.route(other_sites, lambda route: route.fulfill(status=401))
        page.get_by_role('button', name='Refresh data').click()
        expect(page.get_by_role('heading', name='PPE V2 Sign In')).to_be_visible()
        expect(page.get_by_role('alert')).to_have_text('Your session has ended. Sign in again.')


def test_session_expiry_clears_dashboard_without_an_api_error(smoke_origin, admin_account):
    with sync_playwright() as playwright, closing(playwright.chromium.launch()) as browser:
        page = browser.new_page()
        page.clock.install()
        page.goto(smoke_origin)
        page.get_by_label('Email').fill(admin_account['email'])
        page.get_by_label('Password').fill(admin_account['password'])
        with page.expect_response(f'{smoke_origin}/api/v1/auth/login') as login:
            page.get_by_role('button', name='Sign in').click()
        assert login.value.status == 200
        expiration = login.value.json()['expires_at']
        camera = page.get_by_text('Smoke Test Camera', exact=True).first
        expect(camera).to_be_visible()

        remaining = page.evaluate('(expiration) => Date.parse(expiration) - Date.now()', expiration)
        assert remaining > 0
        page.clock.fast_forward(int(remaining) + 1000)

        expect(page.get_by_role('heading', name='PPE V2 Sign In')).to_be_visible()
        expect(page.get_by_role('alert')).to_have_text('Your session has ended. Sign in again.')
        expect(camera).to_have_count(0)
        expect(page.get_by_text('smoke-violation', exact=True)).to_have_count(0)
        expect(page.get_by_label('Password')).to_have_value('')
