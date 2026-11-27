"""Exercise the disposable Compose dashboard over its published loopback origin."""

import argparse
from pathlib import Path
from re import fullmatch

from playwright.sync_api import expect, sync_playwright

from tests.synthetic_compose_ids import EMAIL, NORTH, NORTH_CAMERA, PROBE_VIOLATION, SOUTH, UNASSIGNED

ME = '/api/v1/auth/me'


def login(page, origin, password):
    page.get_by_label('Email').fill(EMAIL)
    page.get_by_label('Password').fill(password)
    with page.expect_response(f'{origin}/api/v1/auth/login') as response:
        page.get_by_role('button', name='Sign in').click()
    assert response.value.status == 200, 'Synthetic login failed'
    return response.value.json()


def verify_dashboard(browser, origin, password):
    page = browser.new_page(service_workers='block')
    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    page.clock.install()
    assert page.goto(origin).ok
    sign_in = page.get_by_role('heading', name='PPE V2 Sign In')
    expect(sign_in).to_be_visible()
    assert page.request.get(origin + '/health/ready').ok
    assert page.request.get(origin + '/internal/v1/cameras').status == 404
    assert page.request.get(origin + ME).status == 401
    assert page.request.get(f'{origin}/api/v1/organizations/{NORTH}/incidents').status == 401
    with page.expect_response(origin + ME) as me:
        session = login(page, origin, password)
    assert me.value.status == 200
    headers = {'Authorization': 'Bearer ' + session['access_token']}
    organization = page.get_by_role('combobox', name='Organization')
    expect(organization).to_be_visible()
    organization.select_option(NORTH)
    north = f'{origin}/api/v1/organizations/{NORTH}'
    south = f'{origin}/api/v1/organizations/{SOUTH}'
    restricted = f'{origin}/api/v1/organizations/{UNASSIGNED}'
    expect(page.get_by_text('North Synthetic Camera', exact=True).first).to_be_visible()
    assert page.request.get(restricted + '/incidents', headers=headers).status == 404
    site = page.request.get(north + '/sites', headers=headers).json()[0]['id']
    cameras = f'/sites/{site}/cameras'
    assert page.request.get(south + cameras, headers=headers).status == 404
    registration = {'name': 'Browser Registered Camera', 'stream_ref': 'stream:lab/registered'}
    assert page.request.post(north + cameras, headers=headers, data=registration).status == 201
    assert page.request.post(north + cameras, headers=headers, data=registration).status == 409
    page.get_by_role('button', name='Refresh data').click()
    expect(page.get_by_text(registration['name'], exact=True)).to_be_visible()

    row = page.get_by_role('row').filter(has_text='North synthetic fixture')
    data = page.request.get(north + '/incidents', headers=headers).json()
    assert data['total'] == 1
    incident = data['items'][0]['id']
    status_path = f'{north}/incidents/{incident}/status'
    assert page.request.patch(status_path, data={'status': 'resolved'}).status == 401
    assert page.request.patch(status_path, headers=headers, data={'status': 'invalid'}).status == 422
    for action, status in (('Acknowledge', 'acknowledged'), ('Resolve', 'resolved')):
        with page.expect_response(status_path) as response:
            row.get_by_role('button', name=action).click()
        assert response.value.status == 200
        expect(row.get_by_text(status, exact=True)).to_be_visible()
    assert page.request.patch(status_path, headers=headers, data={'status': 'resolved'}).status == 409

    organization.select_option(SOUTH)
    expect(page.get_by_text('South Synthetic Camera', exact=True).first).to_be_visible()
    expect(row).to_have_count(0)
    expect(page.get_by_role('button', name='Acknowledge')).to_have_count(0)
    data = page.request.get(south + '/incidents', headers=headers).json()
    viewer_incident = data['items'][0]['id']
    assert page.request.patch(f'{south}/incidents/{viewer_incident}/status', headers=headers,
                              data={'status': 'acknowledged'}).status == 404
    assert page.request.patch(f'{north}/incidents/{viewer_incident}/status', headers=headers,
                              data={'status': 'acknowledged'}).status == 404
    organization.select_option(NORTH)
    expect(row.get_by_text('resolved', exact=True)).to_be_visible()

    with page.expect_response(f'{origin}/api/v1/auth/logout') as logout:
        page.get_by_role('button', name='Sign out').click()
    assert logout.value.status == 204
    assert page.request.get(origin + ME, headers=headers).status == 401
    expect(sign_in).to_be_visible()

    session = login(page, origin, password)
    expect(organization).to_be_visible()
    remaining = page.evaluate('(expires) => Date.parse(expires) - Date.now()', session['expires_at'])
    assert remaining > 0
    page.clock.fast_forward(int(remaining) + 1000)
    expect(sign_in).to_be_visible()
    expect(page.get_by_role('alert')).to_have_text('Your session has ended. Sign in again.')
    expect(organization).to_have_count(0)


def open_north_dashboard(browser, origin, password):
    page = browser.new_page(service_workers='block')
    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    assert page.goto(origin).ok
    session = login(page, origin, password)
    organization = page.get_by_role('combobox', name='Organization')
    expect(organization).to_be_visible()
    organization.select_option(NORTH)
    return page, session, organization


def verify_media(browser, origin, password, state):
    page, session, _ = open_north_dashboard(browser, origin, password)
    row = page.locator('#cameras').get_by_role('row').filter(has_text='North Synthetic Camera')
    row.get_by_role('button', name='Check camera status').click()
    north = f'{origin}/api/v1/organizations/{NORTH}/cameras/{NORTH_CAMERA}/media'
    south = f'{origin}/api/v1/organizations/{SOUTH}/cameras/{NORTH_CAMERA}/media'
    headers = {'Authorization': 'Bearer ' + session['access_token']}
    assert page.request.get(north + '/preview').status == 401
    assert page.request.get(south + '/status', headers=headers).status == 404
    assert page.request.get(south + '/preview', headers=headers).status == 404
    try:
        expect(row.get_by_text(state.title(), exact=True)).to_be_visible(timeout=25000)
    except AssertionError:
        status = page.request.get(north + '/status', headers=headers)
        actual = status.json().get('state') if status.ok else 'unavailable'
        print(f'Synthetic camera API status HTTP {status.status}, state={actual}')
        raise
    if state == 'offline':
        expect(row.get_by_role('button', name='Load video preview')).to_have_count(0)
        assert page.request.get(north + '/preview', headers=headers).status == 503
    else:
        with page.expect_response(north + '/preview') as playback:
            row.get_by_role('button', name='Load video preview').click()
        assert playback.value.status == 200
        assert playback.value.headers['cache-control'] == 'no-store'
        page.wait_for_function("document.querySelector('video')?.readyState >= 2")
    page.get_by_role('button', name='Sign out').click()
    expect(page.locator('video')).to_have_count(0)


def verify_probe_incident(browser, origin, password):
    page, session, organization = open_north_dashboard(browser, origin, password)
    headers = {'Authorization': 'Bearer ' + session['access_token']}
    incidents = f'{origin}/api/v1/organizations/{NORTH}/incidents'
    response = page.request.get(incidents, headers=headers)
    assert response.ok
    events = [item for item in response.json()['items'] if item['violation_type'] == PROBE_VIOLATION]
    assert len(events) == 1 and events[0]['camera_id'] == NORTH_CAMERA and events[0]['status'] == 'open'
    fixture = page.get_by_text(PROBE_VIOLATION.replace('_', ' '), exact=True)
    expect(fixture).to_be_visible()
    expect(fixture).to_have_count(1)
    model_path = f'{origin}/api/v1/organizations/{NORTH}/cameras/{NORTH_CAMERA}/model'
    assert page.request.get(model_path).status == 401
    assert page.request.get(model_path.replace(NORTH, SOUTH), headers=headers).status == 404
    camera = page.locator('#cameras').get_by_role('row').filter(has_text='North Synthetic Camera')
    with page.expect_response(model_path) as assignment:
        camera.get_by_role('button', name='View model assignment').click()
    assert assignment.value.status == 200
    assert set(assignment.value.json()['model_version']) == {'id', 'model_key', 'version'}
    assigned_model = camera.get_by_text('synthetic-compose · Version 1', exact=True)
    expect(assigned_model).to_be_visible()
    expect(camera.get_by_text('Assignment revision 0', exact=True)).to_be_visible()
    organization.select_option(SOUTH)
    expect(page.get_by_text('South Synthetic Camera', exact=True).first).to_be_visible()
    expect(fixture).to_have_count(0)
    expect(assigned_model).to_have_count(0)
    expect(page.get_by_role('button', name='View model assignment')).to_have_count(0)
    print('PPE_COMPOSE_INCIDENT_BROWSER: exactly one probe incident in the authorized organization')
    print('PPE_COMPOSE_MODEL_BROWSER: assigned model visible only to the authorized organization admin')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--env-file', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--media-state', choices=('online', 'offline'))
    mode.add_argument('--expect-probe-incident', action='store_true')
    args = parser.parse_args()
    if not fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', args.origin):
        parser.error('Use the published loopback origin of the disposable Compose project')
    settings = dict(line.split('=', 1) for line in args.env_file.read_text(encoding='ascii').splitlines())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chromium' if args.media_state else None)
        try:
            password = settings['PPE_LAB_LOGIN_PASSWORD']
            if args.media_state:
                verify_media(browser, args.origin, password, args.media_state)
                print(f'PPE_COMPOSE_MEDIA: authorized gateway status {args.media_state} passed')
            elif args.expect_probe_incident:
                verify_probe_incident(browser, args.origin, password)
            else:
                verify_dashboard(browser, args.origin, password)
                print('PPE_COMPOSE_BROWSER: login, tenant isolation, status persistence, logout and expiry passed')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
