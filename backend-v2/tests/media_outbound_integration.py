"""Disposable loopback camera, site publisher, MediaMTX ingress and browser."""

import os
import socket
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from secrets import token_urlsafe
from threading import Thread

import httpx
import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Camera
from app.db.session import SessionLocal
from media_gateway.preview_service import create_preview_service
from tests.browser_smoke import smoke_origin  # noqa: F401
from tests.synthetic_outbound_support import HOST, QUIET, outbound_fixture, process, wait_until

ALIAS = 'stream:smoke-camera'
pytestmark = pytest.mark.skipif(os.getenv('PPE_OUTBOUND_RUN') != '1', reason='Requires test MediaMTX and FFmpeg binaries')


@dataclass(frozen=True)
class MediaHarness:
    origin: str
    camera: str
    organization_path: str
    metrics_origin: str
    token: str = field(repr=False)
    metrics_auth: tuple[str, str] = field(repr=False)
    publisher: list[str] = field(repr=False)


@contextmanager
def run_preview(app):
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        origin = f'http://{HOST}:{sock.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, proxy_headers=False, access_log=False, log_level='warning'))
        thread = Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            wait_until(lambda: server.started)
            yield origin
        finally:
            server.should_exit = True
            thread.join(6)


def reject_publisher(command):
    try:
        result = subprocess.run([*command[:-1], '-t', '1', command[-1]], timeout=12, **QUIET)
    except subprocess.TimeoutExpired:
        pytest.fail('Unauthorized publisher did not exit before the test deadline', pytrace=False)
    assert result.returncode != 0, 'MediaMTX accepted an unauthorized publication'


def ingest_metrics(media):
    with httpx.Client(trust_env=False, timeout=2) as scraper:
        response = scraper.get(media.metrics_origin, auth=media.metrics_auth)
    assert response.status_code == 200
    return response.text.splitlines()


def test_outbound_encrypted_media_and_browser(mount_media, smoke_origin, admin_account):
    media = mount_media
    with httpx.Client(base_url=media.origin, trust_env=False, timeout=2) as client:
        path = f'/internal/v1/cameras/{media.camera}/status'
        params = {'stream_ref': ALIAS}
        headers = {'Authorization': f'Bearer {media.token}'}
        assert client.get(path, params=params).status_code == 401
        assert client.get(path, params={'stream_ref': 'stream:other'}, headers=headers).status_code == 404

        def status():
            return client.get(path, params=params, headers=headers).json()

        assert status()['state'] == 'offline'
        with process(*media.publisher) as publisher:
            try:
                wait_until(lambda: status()['preview_available'])
            except pytest.fail.Exception:
                probe = client.get('/internal/v1/metrics', headers=headers).json()[media.camera]
                ingress_seen = any(line.startswith('srt_conns{') and 'pilot-one' in line
                                   for line in ingest_metrics(media))
                print(f'Synthetic ingress publisher_exit={publisher.poll()} ingest={ingress_seen} gateway={probe}')
                raise
            assert any(line.startswith('paths_inbound_bytes{') and 'pilot-one' in line
                       and float(line.rsplit(' ', 1)[-1]) > 0 for line in ingest_metrics(media))
            metrics = client.get('/internal/v1/metrics', headers=headers).json()[media.camera]
            assert metrics['decoded_frames_total'] >= 2 and metrics['decoded_payload_bytes_total'] > 0
            assert 0 <= metrics['queue_depth'] <= 1 and metrics['processing_latency_ms'] >= 0
            try:
                check_browser(smoke_origin, media.camera, media.organization_path, admin_account)
            except AssertionError:
                probe = client.get('/internal/v1/metrics', headers=headers).json()[media.camera]
                print(f'Synthetic preview diagnostics publisher_exit={publisher.poll()} metrics={probe}')
                raise
        wait_until(lambda: status()['state'] == 'offline')
        assert client.get(path.replace('/status', '/preview'), params=params, headers=headers).status_code == 503
        # A terminated caller can leave an SRT session until the server read deadline.
        # Preserve overridePublisher=false and wait for that session to disappear.
        wait_until(lambda: not any(line.startswith('srt_conns{') and 'path="pilot-one"' in line
                                   for line in ingest_metrics(media)))
        with process(*media.publisher):
            wait_until(lambda: status()['preview_available'])
            assert client.get('/internal/v1/metrics', headers=headers).json()[media.camera]['reconnect_attempts'] > 0


def check_browser(origin, camera, organization_path, admin_account):
    api = f'{origin}/api/v1/{organization_path}/cameras/{camera}/media'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chromium')
        try:
            page = browser.new_page(service_workers='block')
            page.route('**/*', lambda route: route.continue_()
                       if route.request.url.startswith(origin + '/') else route.abort())
            page.goto(origin)
            assert page.request.get(f'{api}/preview').status == 401
            page.get_by_label('Email').fill(admin_account['email'])
            page.get_by_label('Password').fill(admin_account['password'])
            page.get_by_role('button', name='Sign in').click()
            page.get_by_role('button', name='Check camera status').click()
            expect(page.get_by_text('Online', exact=True)).to_be_visible(timeout=15000)
            with page.expect_response(f'{api}/preview') as playback:
                page.get_by_role('button', name='Load video preview').click()
            assert playback.value.status == 200
            assert playback.value.headers['cache-control'] == 'no-store'
            page.wait_for_function("document.querySelector('video')?.readyState >= 2")
            page.get_by_role('button', name='Sign out').click()
            expect(page.locator('video')).to_have_count(0)
        finally:
            browser.close()


@pytest.fixture
def mount_media(smoke_origin, admin_account, tmp_path, monkeypatch, request):
    # Request smoke_origin first so its synthetic camera row is available to bind.
    with SessionLocal() as db:
        camera = db.scalar(select(Camera.id).where(Camera.stream_ref == ALIAS))
    media_token = token_urlsafe(24)
    token_file = tmp_path / 'gateway-token'
    token_file.touch(mode=0o600, exist_ok=False)
    request.addfinalizer(lambda: token_file.unlink(missing_ok=True))
    token_file.write_text(media_token, encoding='ascii')
    with outbound_fixture(tmp_path, width=160, height=96) as media:
        app = create_preview_service({camera: (ALIAS, media.source)}, media_token)
        with run_preview(app) as origin:
            reject_publisher(media.forged_publisher)
            reject_publisher(media.wrong_key_publisher)
            monkeypatch.setattr(get_settings(), 'media_gateway_origin', origin)
            monkeypatch.setattr(get_settings(), 'media_gateway_token_file', str(token_file))
            yield MediaHarness(origin, camera, f'organizations/{admin_account["org_id"]}',
                               media.metrics_origin, media_token, media.metrics_auth, media.publisher)
