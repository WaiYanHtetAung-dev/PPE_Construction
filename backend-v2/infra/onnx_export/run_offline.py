"""Run an approved exporter image without network or production mounts."""

import argparse
import os
import re
import subprocess
from pathlib import Path

EXPECTED = '89e96c1da3c6a413a2d4d5d7ad1a06f485355a5096ea155e3b6d260ed9d3b7dd'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path, help='New directory outside the V2 checkout')
    parser.add_argument('--image', required=True, help='Approved Linux exporter image identified by digest')
    parser.add_argument('--approval', required=True, help='Rights and toolchain approval record ID')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source, destination = args.checkpoint.resolve(strict=True), args.output.resolve()
    if (not re.fullmatch(r'[a-zA-Z0-9._:/-]+@sha256:[a-f0-9]{64}', args.image)
            or not re.fullmatch(r'[a-zA-Z0-9._-]{1,128}', args.approval)):
        parser.error('Use a digest-pinned image and an approval record ID')
    if (not source.is_file() or args.checkpoint.is_symlink() or destination.exists()
            or destination.is_relative_to(root) or any((p / '.git').exists() for p in destination.parents)
            or any(',' in str(p) for p in (source, destination, root))):
        parser.error('Use a regular checkpoint and a new output directory outside the V2 checkout')
    uid = os.getuid() if hasattr(os, 'getuid') else 10001
    gid = os.getgid() if hasattr(os, 'getgid') else 10001
    if uid == 0:
        parser.error('Run the offline export launcher as a non-root user')
    destination.mkdir()
    docker = [
        'docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
        f'--user={uid}:{gid}', '--cap-drop=ALL', '--security-opt=no-new-privileges',
        '--cpus=2', '--memory=6g', '--pids-limit=64', '--ulimit=fsize=268435456:268435456',
        '--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=1g,mode=1777',
        '--env=HOME=/tmp', '--env=YOLO_CONFIG_DIR=/tmp', '--env=YOLO_AUTOINSTALL=False',
        '--env=OMP_NUM_THREADS=2', '--env=OPENBLAS_NUM_THREADS=2',
        '--mount', f'type=bind,source={source},target=/input/finalboss.pt,readonly',
        '--mount', f'type=bind,source={destination},target=/output',
        '--mount', f'type=bind,source={Path(__file__).with_name("export.py")},target=/export.py,readonly',
        '--entrypoint=python', args.image, '/export.py', EXPECTED, args.approval, args.image,
    ]
    subprocess.run(docker, check=True)


if __name__ == '__main__':
    main()
