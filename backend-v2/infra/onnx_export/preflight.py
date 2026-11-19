"""Checkpoint-free readiness probe; runs inside the hashed Linux exporter image."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.metadata import distributions, version
from pathlib import Path
from urllib.parse import unquote, urlsplit

LOCK = Path('/build/requirements.lock')
WHEELS = Path('/build/wheels')
VERSIONS = ('8.4.102', '8.4.96')
PIN = re.compile(r'([A-Za-z0-9_.-]+)(?:\[[a-zA-Z0-9_,.-]+\])?==([A-Za-z0-9_.!+-]+)')
HASH = re.compile(r'--hash=sha256:[0-9a-f]{64}')


def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def parse_lock(content, expected_version):
    pins = {}
    content = content.replace('\r\n', '\n')
    for line in content.replace('\\\n', ' ').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        requirement, *hashes = line.split()
        match = PIN.fullmatch(requirement)
        if match is None or not hashes or not all(HASH.fullmatch(item) for item in hashes):
            raise ValueError('Every lock entry must be an exact package pin with SHA-256 wheel hashes')
        package = normalize(match[1])
        if package in pins:
            raise ValueError('Duplicate package in wheel lock')
        pins[package] = match[2]
    if (expected_version not in VERSIONS or pins.get('ultralytics') != expected_version
            or not {'torch', 'onnx', 'numpy'} <= pins.keys()
            or not {'opencv-python', 'opencv-python-headless'} & pins.keys()):
        raise ValueError('Lock does not provide the approved CPU exporter profile')
    return pins


def verify_runtime(expected_version, expected_lock):
    if os.getuid() == 0 or set(os.listdir('/sys/class/net')) != {'lo'}:
        raise ValueError('Exporter must run unprivileged with only the loopback interface')
    if (not os.statvfs('/').f_flag & os.ST_RDONLY
            or os.environ.get('YOLO_AUTOINSTALL') != 'False'):
        raise ValueError('Exporter must run with a read-only filesystem and auto-install disabled')
    forbidden = ('DATABASE_URL', 'PGPASSWORD', 'PGSERVICEFILE', 'AWS_SECRET_ACCESS_KEY',
                 'GOOGLE_APPLICATION_CREDENTIALS', 'AZURE_CLIENT_SECRET', 'HF_TOKEN', 'GH_TOKEN')
    if any(os.environ.get(name) for name in forbidden):
        raise ValueError('Exporter environment contains credential configuration')
    content = LOCK.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_lock:
        raise ValueError('Exporter wheel lock does not match the approved digest')
    pins = parse_lock(content.decode('utf-8'), expected_version)
    installed = {normalize(item.metadata['Name']) for item in distributions()}
    if installed - pins.keys() - {'pip', 'setuptools', 'wheel'}:
        raise ValueError('Exporter image contains packages outside the approved lock')
    if any(version(name) != pinned for name, pinned in pins.items()):
        raise ValueError('Installed packages differ from the approved lock')
    return pins


def verify_install_plan(pins, dependencies):
    resolved = {}
    for item in dependencies:
        meta = item['metadata']
        uri = urlsplit(item['download_info']['url'])
        path = Path(unquote(uri.path))
        if (uri.scheme != 'file' or uri.netloc or path.parent != WHEELS
                or path.suffix.lower() != '.whl'):
            raise ValueError('Resolver selected a dependency outside the approved wheelhouse')
        package = normalize(meta['name'])
        if package in resolved:
            raise ValueError('Offline resolver reported a duplicate package')
        resolved[package] = meta['version']
    if resolved != pins:
        raise ValueError('Offline dependency resolution did not match the full lock')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', choices=VERSIONS)
    parser.add_argument('lock_sha256')
    args = parser.parse_args()
    pins = verify_runtime(args.version, args.lock_sha256)
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / 'install.json'
        subprocess.run([
            sys.executable, '-m', 'pip', '--isolated', '--disable-pip-version-check',
            'install', '--dry-run', '--ignore-installed', '--no-index', '--only-binary=:all:',
            '--require-hashes', '--find-links', str(WHEELS), '--report', str(report), '-r', str(LOCK),
        ], check=True, stdout=subprocess.DEVNULL)
        verify_install_plan(pins, json.loads(report.read_text(encoding='utf-8'))['install'])
    print(json.dumps({'version': args.version, 'lock_sha256': args.lock_sha256,
                      'verified_wheel_count': len(pins), 'checkpoint_loaded': False}))


if __name__ == '__main__':
    main()
