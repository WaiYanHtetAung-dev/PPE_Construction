"""Exercise the disposable Compose dashboard over its published loopback origin."""

import argparse
from pathlib import Path
from re import fullmatch

from playwright.sync_api import expect, sync_playwright

from tests.synthetic_compose_seed import EMAIL, NORTH, SOUTH, UNASSIGNED

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--env-file', required=True, type=Path)
    args = parser.parse_args()
    if not fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', args.origin):
        parser.error('Use the published loopback origin of the disposable Compose project')
    settings = dict(line.split('=', 1) for line in args.env_file.read_text(encoding='ascii').splitlines())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            verify_dashboard(browser, args.origin, settings['PPE_LAB_LOGIN_PASSWORD'])
        finally:
            browser.close()
    print('PPE_COMPOSE_BROWSER: login, tenant isolation, status persistence, logout and expiry passed')


if __name__ == '__main__':
    main()
