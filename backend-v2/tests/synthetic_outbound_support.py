"""Run a disposable RTSP camera and authenticated SRT ingress on loopback."""

import json
import os
import socket
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from time import monotonic, sleep

import pytest

from media_gateway.network_source import central_rtsp_source
from media_gateway.sampler import FrameSource
from media_gateway.site_publisher import publish_command

HOST = '127.0.0.1'
QUIET = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
         'env': {key: value for key, value in os.environ.items() if key.upper() != 'FFREPORT'}}


@dataclass(frozen=True, repr=False)
class OutboundFixture:
    source: FrameSource
    publisher: list[str]
    forged_publisher: list[str]
    wrong_key_publisher: list[str]
    metrics_origin: str
    metrics_auth: tuple[str, str]


def wait_until(check, timeout=15):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if check():
            return
        sleep(0.1)
    pytest.fail('Synthetic media did not reach the expected state')


def ports():
    sockets = [socket.socket(socket.AF_INET, mode) for mode in
               (socket.SOCK_STREAM, socket.SOCK_STREAM, socket.SOCK_STREAM, socket.SOCK_DGRAM)]
    try:
        for sock in sockets:
            sock.bind((HOST, 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def listening(port):
    try:
        with socket.create_connection((HOST, port), timeout=0.2):
            return True
    except OSError:
        return False


@contextmanager
def process(*args):
    with subprocess.Popen(args, **QUIET) as child:
        try:
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    child.kill()


def media_config(path, rtsp, users, paths, srt=None, metrics=None):
    settings = dict(logLevel='error', rtspAddress=f'{HOST}:{rtsp}', rtspTransports=['tcp'],
                    authInternalUsers=users, paths=paths, rtmp=False, hls=False, webrtc=False,
                    moq=False, srt=srt is not None, metrics=metrics is not None, readTimeout='4s',
                    pathDefaults={'overridePublisher': False})
    if srt is not None:
        settings['srtAddress'] = f'{HOST}:{srt}'
    if metrics is not None:
        settings['metricsAddress'] = f'{HOST}:{metrics}'
    path.touch(mode=0o600, exist_ok=False)
    path.write_text(json.dumps(settings), encoding='ascii')  # JSON is valid YAML.
    return path


def permission(user, password, action, path=''):
    return {'user': user, 'pass': password, 'permissions': [{'action': action, 'path': path}]}


@contextmanager
def outbound_fixture(root, *, width, height):
    binary = str(Path(os.environ['PPE_MEDIAMTX']).resolve(strict=True))
    lan, central, metrics, srt = ports()
    lan_pass, pub_pass, other_pass, reader_pass, metrics_pass, phrase, other_phrase = (
        token_urlsafe(24) for _ in range(7)
    )
    lan_url = f'rtsp://camera:{lan_pass}@{HOST}:{lan}/fixture'
    fixture = ('ffmpeg', '-nostdin', '-loglevel', 'quiet', '-re', '-f', 'lavfi', '-i',
               f'testsrc2=size={width}x{height}:rate=10', '-c:v', 'libx264', '-threads', '1',
               '-preset', 'ultrafast', '-tune', 'zerolatency', '-g', '10', '-f', 'rtsp',
               '-rtsp_transport', 'tcp', lan_url)
    with TemporaryDirectory(dir=root) as directory:
        root = Path(directory)
        lan_config = media_config(root / 'lan.yml', lan, [permission('camera', lan_pass, action, 'fixture')
                                  for action in ('publish', 'read')], {'fixture': {'source': 'publisher'}})
        central_config = media_config(root / 'central.yml', central, [
            permission('publisher-one', pub_pass, 'publish', 'pilot-one'),
            permission('publisher-two', other_pass, 'publish', 'pilot-two'),
            permission('reader', reader_pass, 'read', 'pilot-one'),
            permission('observer', metrics_pass, 'metrics'),
        ], {'pilot-one': {'source': 'publisher', 'srtPublishPassphrase': phrase},
            'pilot-two': {'source': 'publisher', 'srtPublishPassphrase': other_phrase}}, srt=srt, metrics=metrics)
        harness = OutboundFixture(
            source=central_rtsp_source(HOST, central, 'pilot-one', 'reader', reader_pass),
            publisher=publish_command(lan_url, HOST, srt, 'pilot-one', 'publisher-one', pub_pass, phrase),
            forged_publisher=publish_command(lan_url, HOST, srt, 'pilot-two', 'publisher-one', pub_pass, other_phrase),
            wrong_key_publisher=publish_command(lan_url, HOST, srt, 'pilot-one', 'publisher-one', pub_pass, other_phrase),
            metrics_origin=f'http://{HOST}:{metrics}/metrics',
            metrics_auth=('observer', metrics_pass),
        )
        with process(binary, str(lan_config)), process(binary, str(central_config)):
            wait_until(lambda: listening(lan) and listening(central))
            with process(*fixture):
                sleep(1.5)
                yield harness
