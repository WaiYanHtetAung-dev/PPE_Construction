"""Launch the fixed synthetic media services for the disposable Compose lab."""

import argparse
import os
import signal
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path
from re import fullmatch
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
from urllib.request import ProxyHandler, Request, build_opener

from tests.synthetic_compose_ids import NORTH_ALIAS, NORTH_CAMERA, SECRET_PATTERN
from tests.synthetic_streams import HOST, camera_command, media_config, permission

CENTRAL = 'central-media'
RTSP_PORT, SRT_PORT, LOCAL_READER, PREVIEW_PORT = 8554, 8890, 18554, 8445
PATH = 'pilot-north'


def credential(name):
    value = os.environ.get('PPE_LAB_' + name, '')
    if not fullmatch(SECRET_PATTERN, value):
        raise ValueError('Invalid synthetic lab credential')
    return value


@contextmanager
def child(*args):
    quiet = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    with subprocess.Popen(args, env={'PATH': os.environ['PATH']}, **quiet) as proc:
        try:
            yield proc
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()


def check_port(port, host=HOST):
    with socket.create_connection((host, port), timeout=0.5):
        pass


def wait_for_port(port):
    end = monotonic() + 8
    while monotonic() < end:
        try:
            check_port(port)
            return
        except OSError:
            sleep(0.1)
    raise OSError('Synthetic local listener did not become ready')


def media_read_address():
    # Route lookup selects the ingress interface on the network shared with
    # the API. UDP connect without a send does not open an application session.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(('api', 8000))
        return route.getsockname()[0]


def ingress(root):
    config = media_config(root / 'central.yml', RTSP_PORT, [
        permission('publisher', credential('PUBLISHER_PASSWORD'), 'publish', PATH),
        permission('reader', credential('READER_PASSWORD'), 'read', PATH),
    ], {PATH: {'source': 'publisher', 'srtPublishPassphrase': credential('SRT_PASSPHRASE')}},
        srt=SRT_PORT, rtsp_host=media_read_address(), srt_host='0.0.0.0')
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with child('mediamtx', str(config)) as server:
        while not stop.wait(0.2):
            if server.poll() is not None:
                raise OSError('Synthetic ingress exited')


def site(root):
    from media_gateway.site_publisher import main as run_publisher

    lan_password = token_urlsafe(24)
    lan_url = f'rtsp://camera:{lan_password}@{HOST}:{RTSP_PORT}/fixture'
    config = media_config(root / 'lan.yml', RTSP_PORT, [
        permission('camera', lan_password, action, 'fixture') for action in ('read', 'publish')
    ], {'fixture': {'source': 'publisher'}})
    for name, value in (
        ('SITE_CAMERA_RTSP_FILE', lan_url),
        ('SITE_PUBLISHER_PASSWORD_FILE', credential('PUBLISHER_PASSWORD')),
        ('SITE_SRT_PASSPHRASE_FILE', credential('SRT_PASSPHRASE')),
    ):
        file = root / name
        file.write_text(value, encoding='ascii')
        os.environ[name] = str(file)
    os.environ.update(SITE_SRT_HOST=CENTRAL, SITE_SRT_PORT=str(SRT_PORT),
                      SITE_STREAM_PATH=PATH, SITE_PUBLISHER_USER='publisher')
    with child('mediamtx', str(config)):
        wait_for_port(RTSP_PORT)
        with child(*camera_command(lan_url, 160, 64)):
            sleep(1)
            run_publisher()


def preview(_root):
    import uvicorn
    from media_gateway.network_source import central_rtsp_source
    from media_gateway.preview_service import create_preview_service

    # The proxy forwards exactly one interleaved RTSP port. The decoder still
    # accepts only loopback, and site RTSP only listens on its own loopback.
    source = central_rtsp_source(HOST, LOCAL_READER, PATH, 'reader', credential('READER_PASSWORD'))
    app = create_preview_service({NORTH_CAMERA: (NORTH_ALIAS, source)}, credential('MEDIA_TOKEN'))
    with child('socat', f'TCP-LISTEN:{LOCAL_READER},bind={HOST},reuseaddr,fork,max-children=6',
               f'TCP:{CENTRAL}:{RTSP_PORT},connect-timeout=2'):
        wait_for_port(LOCAL_READER)
        uvicorn.run(app, host=HOST, port=PREVIEW_PORT, access_log=False, proxy_headers=False)


def check_preview(_root):
    origin = f'http://{HOST}:{PREVIEW_PORT}'
    req = Request(origin + '/internal/v1/metrics',
                  headers={'Authorization': 'Bearer ' + credential('MEDIA_TOKEN')})
    with build_opener(ProxyHandler({})).open(req, timeout=1) as reply:
        if reply.status != 200:
            raise OSError('Synthetic preview is unavailable')


def check_uplink(_root):
    host = socket.gethostbyname(CENTRAL)
    try:
        check_port(RTSP_PORT, host)
    except OSError:
        print('PPE_COMPOSE_UPLINK: site cannot reach the central RTSP reader')
        return
    raise ValueError('Central RTSP is reachable from the site uplink')


def api(_root):
    import uvicorn

    if os.environ.get('APP_ENV') != 'synthetic-compose':
        raise ValueError('Expected a synthetic Compose API')
    Path('/tmp/ppe-lab-preview-token').write_text(credential('MEDIA_TOKEN'), encoding='ascii')
    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, access_log=False, proxy_headers=False)


def main():
    actions = {'api': api, 'site': site, 'ingress': ingress, 'preview': preview,
               'check-ingress': lambda _: check_port(RTSP_PORT, media_read_address()),
               'check-preview': check_preview, 'check-uplink': check_uplink}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=actions)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        with TemporaryDirectory() as directory:
            actions[args.service](Path(directory))
    except (OSError, ValueError):
        raise SystemExit(f'Synthetic {args.service} service failed') from None


if __name__ == '__main__':
    main()
