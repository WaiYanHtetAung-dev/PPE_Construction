"""Site-local RTSP-to-SRT publisher for an operator-provisioned camera."""

import os
import signal
import subprocess
from ipaddress import IPv4Address
from pathlib import Path
from re import fullmatch
from threading import Event
from time import monotonic
from urllib.parse import urlencode, urlsplit

from media_gateway.network_source import identifier_secret, stream_path


def secret_file(path: str, limit: int = 512) -> str:
    with Path(path).open(encoding='ascii') as source:
        value = source.read(limit + 1)
    if len(value) > limit or not value.strip():
        raise ValueError('Invalid media configuration file')
    return value.strip()


def publish_command(camera_url, central_host, port, path, username, password, passphrase):
    camera = urlsplit(camera_url)
    lan = IPv4Address(camera.hostname or '')
    if (camera.scheme != 'rtsp' or not (lan.is_private or lan.is_loopback)
            or lan.is_unspecified or lan.is_multicast or lan.is_reserved or camera.fragment
            or not camera.path or any(not 33 <= ord(char) <= 126 for char in camera_url)):
        raise ValueError('Invalid camera LAN configuration')
    if (not 1 <= port <= 65535 or not fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', central_host)
            or not fullmatch(r'[A-Za-z0-9_-]{1,48}', username)):
        raise ValueError('Invalid outbound publisher configuration')
    query = urlencode({
        'streamid': f'publish:{stream_path(path)}:{username}:{identifier_secret(password)}',
        'passphrase': identifier_secret(passphrase), 'pbkeylen': 32, 'pkt_size': 1316,
        'mode': 'caller', 'connect_timeout': 3000, 'rw_timeout': 5000000,
    }, safe=':/')
    return ['ffmpeg', '-nostdin', '-loglevel', 'quiet', '-rtsp_transport', 'tcp', '-timeout', '5000000',
            '-i', camera_url, '-map', '0:v:0', '-c:v', 'copy', '-f', 'mpegts',
            f'srt://{central_host}:{port}?{query}']


def main():
    command = publish_command(
        secret_file(os.environ['SITE_CAMERA_RTSP_FILE']), os.environ['SITE_SRT_HOST'],
        int(os.environ['SITE_SRT_PORT']), os.environ['SITE_STREAM_PATH'], os.environ['SITE_PUBLISHER_USER'],
        secret_file(os.environ['SITE_PUBLISHER_PASSWORD_FILE']),
        secret_file(os.environ['SITE_SRT_PASSPHRASE_FILE']),
    )
    stopping = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    delay = 0.5
    while not stopping.is_set():
        started = monotonic()
        with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL) as publisher:
            try:
                while publisher.poll() is None and not stopping.wait(0.25):
                    pass
            finally:
                if publisher.poll() is None:
                    publisher.terminate()
                    try:
                        publisher.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        publisher.kill()
        if monotonic() - started >= 8:
            delay = 0.5
        stopping.wait(delay)
        delay = min(8, delay * 2)


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError):
        raise SystemExit('Site publisher startup failed') from None
