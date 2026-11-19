"""Run an approved exporter image without network or production mounts."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

EXPECTED = '89e96c1da3c6a413a2d4d5d7ad1a06f485355a5096ea155e3b6d260ed9d3b7dd'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path, help='New directory outside the V2 checkout')
    parser.add_argument('--toolchains', type=Path, required=True)
    parser.add_argument('--version', choices=['8.4.102', '8.4.96'], required=True)
    parser.add_argument('--mode', choices=['export', 'reference'], default='export')
    parser.add_argument('--corpus-manifest', type=Path)
    parser.add_argument('--corpus-root', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source, destination = args.checkpoint.resolve(strict=True), args.output.resolve()
    profile = json.loads(args.toolchains.read_text(encoding='utf-8'))[args.version]
    if set(profile) != {'image', 'lock_sha256', 'approval'}:
        parser.error('Toolchain requires an approved image, lock digest and approval record ID')
    image, lock, approval = (profile[name] for name in ('image', 'lock_sha256', 'approval'))
    if (not re.fullmatch(r'[a-zA-Z0-9._:/-]+@sha256:[a-f0-9]{64}', image)
            or not re.fullmatch(r'[a-f0-9]{64}', lock)
            or not re.fullmatch(r'[a-zA-Z0-9._-]{1,128}', approval)
            or approval.startswith('REPLACE-')):
        parser.error('Use a digest-pinned image, lock digest and a reviewed approval record ID')
    mounts = []
    if args.mode == 'reference':
        if args.version != '8.4.96' or not args.corpus_manifest or not args.corpus_root:
            parser.error('V1 reference requires the approved 8.4.96 profile and external corpus')
        from corpus import load_corpus
        corpus_root = args.corpus_root.resolve(strict=True)
        manifest = args.corpus_manifest.resolve(strict=True)
        if not corpus_root.is_dir() or any(',' in str(p) for p in (corpus_root, manifest)):
            parser.error('Use a dedicated corpus directory and manifest')
        corpus, _ = load_corpus(manifest, corpus_root)
        if set(corpus_root.iterdir()) != {corpus_root / row['file'] for row in corpus['samples']}:
            parser.error('Corpus root must contain only the approved images')
        mounts = ['--mount', f'type=bind,source={manifest},target=/corpus.json,readonly',
                  '--mount', f'type=bind,source={corpus_root},target=/corpus,readonly']
    elif args.corpus_manifest or args.corpus_root:
        parser.error('Corpus mounts are allowed only in reference mode')
    if (not source.is_file() or args.checkpoint.is_symlink() or destination.exists()
            or destination.is_relative_to(root) or any((p / '.git').exists() for p in destination.parents)
            or any(',' in str(p) for p in (source, destination, root))):
        parser.error('Use a regular checkpoint and a new output directory outside the V2 checkout')
    uid = os.getuid() if hasattr(os, 'getuid') else 10001
    gid = os.getgid() if hasattr(os, 'getgid') else 10001
    if uid == 0:
        parser.error('Run the offline export launcher as a non-root user')
    subprocess.run(['docker', 'image', 'inspect', image], check=True, stdout=subprocess.DEVNULL)
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
        *[arg for code in ('export.py', 'reference.py', 'corpus.py')
          for arg in ('--mount', f'type=bind,source={Path(__file__).with_name(code)},target=/tool/{code},readonly')],
        *mounts, '--entrypoint=python', image, '/tool/export.py', EXPECTED, approval, image,
        args.version, lock, args.mode,
    ]
    subprocess.run(docker, check=True)


if __name__ == '__main__':
    main()
