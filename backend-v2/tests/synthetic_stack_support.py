"""Owned loopback TLS listeners and disposable mounts for stack acceptance."""

import asyncio
import ipaddress
import os
import socket
import ssl
import subprocess
import sys
from contextlib import aclosing, asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from media_gateway.video_source import local_video_source


@asynccontextmanager
async def paced_video(path, fps, observe, observe_read=None):
    """Loop a generated clip with continuous PTS and no catch-up bursts."""
    clock = asyncio.get_running_loop().time

    async def frames():
        offset, index, previous_pts, released = 0.0, 0, None, None
        while True:
            count = 0
            read_started = clock()
            async with local_video_source(path) as decoded:
                async for frame in decoded:
                    if observe_read is not None:
                        observe_read(clock() - read_started, count == 0)
                    pts = offset + frame.source_timestamp
                    if previous_pts is not None:
                        gap = pts - previous_pts
                        if gap <= 0:
                            raise ValueError('Fixture presentation time did not advance')
                        await asyncio.sleep(max(0, released + gap - clock()))
                    now = clock()
                    observe(now, None if released is None else now - released)
                    yield replace(frame, source_timestamp=pts, index=index)
                    previous_pts, released = pts, now
                    index += 1
                    count += 1
                    read_started = clock()
            if count != fps:
                raise ValueError('Unexpected frame count in one-second fixture')
            offset += 1.0

    async with aclosing(frames()) as stream:
        yield stream

def temporary_tls(root):
    now = datetime.now(UTC)
    ca_key, tls_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(2))
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Disposable PPE test CA')])

    def certificate(subject, key):
        return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1)))

    ca = (certificate(issuer, ca_key).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), True))
    tls = (certificate(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')]), tls_key)
           .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
           .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
           .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
           .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False))
    certfile, keyfile = root / 'listener.pem', root / 'listener.key'
    certfile.write_bytes(tls.sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))
    keyfile.touch(mode=0o600, exist_ok=False)
    keyfile.write_bytes(tls_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    ca_file = root / 'ca.pem'
    ca_file.write_bytes(ca.sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))
    context = ssl.create_default_context(cafile=str(ca_file))
    return context, certfile, keyfile, ca_file


@contextmanager
def readonly_bind(source, target):
    target.mkdir()
    privilege = [] if os.geteuid() == 0 else ['sudo', '-n']
    subprocess.run([*privilege, 'mount', '--bind', str(source), str(target)], check=True, timeout=10)
    try:
        subprocess.run([*privilege, 'mount', '-o', 'remount,bind,ro,nosuid,nodev,noexec', str(target)],
                       check=True, timeout=10)
        assert os.statvfs(target).f_flag & os.ST_RDONLY
        yield target
    finally:
        subprocess.run([*privilege, 'umount', str(target)], check=True, timeout=10)


def loopback_socket(port=0):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', port))
    listener.listen()
    return listener


class TestListener(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield


async def wait_for(check, timeout=10):
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.015)


@asynccontextmanager
async def listener(app, cert, key, *, port=0):
    with loopback_socket(port) as sock:
        origin = f'https://127.0.0.1:{sock.getsockname()[1]}'
        server = TestListener(uvicorn.Config(app, ssl_certfile=str(cert), ssl_keyfile=str(key),
                                             access_log=False, log_level='warning', proxy_headers=False))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            await wait_for(lambda: server.started or task.done())
            assert server.started, 'Synthetic TLS listener did not start'
            yield origin
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=8)


@asynccontextmanager
async def worker_process(cert, key, settings, context):
    with loopback_socket() as sock:
        worker = RestartableWorker(sock, cert, key, settings, context)
        try:
            await worker.start()
            yield worker
        finally:
            await worker.stop()


class RestartableWorker:
    def __init__(self, sock, cert, key, settings, context):
        # The parent retains the loopback socket across child process restarts.
        self.sock = sock
        self.cert, self.key = cert, key
        self.context = context
        self.origin = f'https://127.0.0.1:{sock.getsockname()[1]}'
        self.process = None
        # Keep database and CI credentials outside the isolated worker process.
        self.env = {k: os.environ[k] for k in ('PATH', 'PYTHONPATH', 'LD_LIBRARY_PATH') if k in os.environ}
        self.env.update(settings, PYTHONUNBUFFERED='1')

    async def start(self):
        assert self.process is None, 'Stop the existing worker before restarting'
        bootstrap = """
import socket
import sys
import uvicorn

fd, cert, key = sys.argv[1:]
with socket.socket(socket.AF_INET, socket.SOCK_STREAM, fileno=int(fd)) as listener:
    config = uvicorn.Config(
        'tests.synthetic_worker_profile:worker_factory', factory=True,
        ssl_certfile=cert, ssl_keyfile=key, access_log=False,
        proxy_headers=False, log_level='warning',
    )
    uvicorn.Server(config).run(sockets=[listener])
"""
        diagnostic = self.key.parent / 'worker-stderr.log'
        with diagnostic.open('wb') as log:
            fd = self.sock.fileno()
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, '-B', '-c', bootstrap, str(fd), str(self.cert), str(self.key),
                env=self.env, pass_fds=(fd,), stdout=asyncio.subprocess.DEVNULL, stderr=log,
            )
        async with asyncio.timeout(12), httpx.AsyncClient(verify=self.context, trust_env=False,
                                                          timeout=0.25) as client:
            while True:
                if self.process.returncode is not None:
                    # Bootstrap receives only ephemeral paths and no database or CI credentials.
                    message = diagnostic.read_text(encoding='utf-8', errors='replace')[-2000:]
                    raise AssertionError(f'Inference worker startup failed: {message}')
                try:
                    if (await client.get(self.origin)).status_code == 404:
                        return
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.05)

    async def stop(self):
        process = self.process
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=8)
        except TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=3)
        self.process = None
