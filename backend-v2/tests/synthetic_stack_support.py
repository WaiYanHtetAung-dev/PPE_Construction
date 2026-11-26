"""Owned loopback TLS listeners and disposable mounts for stack acceptance."""

import asyncio
import ipaddress
import os
import socket
import ssl
import subprocess
import sys
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


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


def loopback_socket():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
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
async def listener(app, cert, key):
    with loopback_socket() as sock:
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
        origin = f'https://127.0.0.1:{sock.getsockname()[1]}'
        env = os.environ.copy()
        # Keep database and CI credentials outside the isolated worker process.
        env = {k: env[k] for k in ('PATH', 'PYTHONPATH', 'LD_LIBRARY_PATH') if k in env}
        env.update(settings, PYTHONUNBUFFERED='1')
        bootstrap = """
import socket
import sys
import uvicorn

fd, cert, key = sys.argv[1:]
with socket.socket(socket.AF_INET, socket.SOCK_STREAM, fileno=int(fd)) as listener:
    config = uvicorn.Config(
        'inference_worker.service:from_environment', factory=True,
        ssl_certfile=cert, ssl_keyfile=key, access_log=False,
        proxy_headers=False, log_level='warning',
    )
    uvicorn.Server(config).run(sockets=[listener])
"""
        diagnostic = key.parent / 'worker-stderr.log'
        with diagnostic.open('wb') as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-B', '-c', bootstrap, str(sock.fileno()), str(cert), str(key),
                env=env, pass_fds=(sock.fileno(),), stdout=asyncio.subprocess.DEVNULL, stderr=log,
            )
        sock.close()
        try:
            async with asyncio.timeout(12), httpx.AsyncClient(verify=context, trust_env=False, timeout=0.25) as client:
                while True:
                    if process.returncode is not None:
                        # Bootstrap receives only ephemeral paths and no database or CI credentials.
                        message = diagnostic.read_text(encoding='utf-8', errors='replace')[-2000:]
                        raise AssertionError(f'Inference worker startup failed: {message}')
                    try:
                        if (await client.get(origin)).status_code == 404:
                            break
                    except httpx.TransportError:
                        await asyncio.sleep(0.05)
            yield origin
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=8)
            except TimeoutError:
                process.kill()
                await process.wait()
