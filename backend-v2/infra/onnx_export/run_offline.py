"""Run an approved exporter image without network or production mounts."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

EXPECTED = '89e96c1da3c6a413a2d4d5d7ad1a06f485355a5096ea155e3b6d260ed9d3b7dd'


def require_approval(directory, approval_id, purpose, bindings):
    if (not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', approval_id)
            or approval_id.startswith('REPLACE-') or '..' in approval_id):
        raise ValueError('Invalid approval record ID')
    path = directory / (approval_id + '.json')
    if path.is_symlink() or not path.is_file():
        raise ValueError('Required external approval record is missing')
    with path.open('rb') as source:
        data = source.read(65537)
    if len(data) > 65536:
        raise ValueError('Approval record too large')
    record = json.loads(data)
    if (record.get('id') != approval_id or record.get('status') != 'approved'
            or record.get('purpose') != purpose or record.get('bindings') != bindings):
        raise ValueError('External approval record does not match requested inputs')


def inspect_image(image):
    result = subprocess.run(['docker', 'image', 'inspect', image], check=True,
                            capture_output=True, text=True)
    entries = json.loads(result.stdout)
    digest = image.rsplit('@', 1)[1]
    if (len(entries) != 1 or entries[0].get('Os') != 'linux'
            or entries[0].get('Architecture') != 'amd64'
            or (entries[0].get('Config') or {}).get('Volumes')
            or not any(item.rsplit('@', 1)[-1] == digest for item in entries[0].get('RepoDigests') or [])):
        raise ValueError('Local image platform, digest or implicit volumes are invalid')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path, help='New directory outside the V2 checkout')
    parser.add_argument('--toolchains', type=Path, required=True)
    parser.add_argument('--version', choices=['8.4.102', '8.4.96'], required=True)
    parser.add_argument('--mode', choices=['export', 'reference'], default='export')
    parser.add_argument('--approval-dir', type=Path, required=True, help='External reviewed approval records')
    parser.add_argument('--rights-approval', required=True, help='Reviewed checkpoint usage approval record ID')
    parser.add_argument('--preflight-only', action='store_true', help='Check readiness without mounting the checkpoint')
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
            or approval.startswith('REPLACE-')
            or not re.fullmatch(r'[a-zA-Z0-9._-]{1,128}', args.rights_approval)
            or args.rights_approval.startswith('REPLACE-')):
        parser.error('Use a digest-pinned image, lock digest, toolchain approval and rights approval')
    approvals = args.approval_dir.resolve(strict=True)
    if not approvals.is_dir() or approvals.is_relative_to(root) or any((p / '.git').exists() for p in (approvals, *approvals.parents)):
        parser.error('Approval records must be in an external directory')
    require_approval(approvals, args.rights_approval, 'checkpoint-rights', {'checkpoint_sha256': EXPECTED})
    require_approval(approvals, approval, 'exporter-toolchain',
                     {'version': args.version, 'image': image, 'lock_sha256': lock})
    mounts = []
    if args.mode == 'reference':
        if args.version != '8.4.96' or not args.corpus_manifest or not args.corpus_root:
            parser.error('V1 reference requires the approved 8.4.96 profile and external corpus')
        from corpus import load_corpus
        corpus_root = args.corpus_root.resolve(strict=True)
        manifest = args.corpus_manifest.resolve(strict=True)
        if not corpus_root.is_dir() or any(',' in str(p) for p in (corpus_root, manifest)):
            parser.error('Use a dedicated corpus directory and manifest')
        corpus, corpus_hash = load_corpus(manifest, corpus_root)
        require_approval(approvals, corpus['approval'], 'corpus', {'corpus_sha256': corpus_hash})
        for row in corpus['samples']:
            require_approval(approvals, row['usage_authorization'], 'fixture', {'image_sha256': row['sha256']})
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
    with source.open('rb') as checkpoint:
        if hashlib.file_digest(checkpoint, 'sha256').hexdigest() != EXPECTED:
            parser.error('Original Finalboss checkpoint digest mismatch')
    inspect_image(image)
    sandbox = [
        'docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
        f'--user={uid}:{gid}', '--cap-drop=ALL', '--security-opt=no-new-privileges',
        '--cpus=2', '--memory=6g', '--memory-swap=6g', '--pids-limit=64', '--ulimit=fsize=268435456:268435456',
        '--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=1g,mode=1777',
        '--env=HOME=/tmp', '--env=YOLO_CONFIG_DIR=/tmp', '--env=YOLO_AUTOINSTALL=False',
        '--env=PYTHONNOUSERSITE=1',
        '--env=OMP_NUM_THREADS=2', '--env=OPENBLAS_NUM_THREADS=2',
    ]
    probe = Path(__file__).with_name('preflight.py')
    subprocess.run([
        *sandbox, '--mount', f'type=bind,source={probe},target=/tool/preflight.py,readonly',
        '--entrypoint=python', image, '/tool/preflight.py', args.version, lock,
    ], check=True)
    if args.preflight_only:
        return
    destination.mkdir()
    docker = [
        *sandbox, '--mount', f'type=bind,source={source},target=/input/finalboss.pt,readonly',
        '--mount', f'type=bind,source={destination},target=/output',
        *[arg for code in ('export.py', 'reference.py', 'corpus.py', 'preflight.py')
          for arg in ('--mount', f'type=bind,source={Path(__file__).with_name(code)},target=/tool/{code},readonly')],
        *mounts, '--entrypoint=python', image, '/tool/export.py', EXPECTED, approval, image,
        args.version, lock, args.mode, args.rights_approval,
    ]
    subprocess.run(docker, check=True)


if __name__ == '__main__':
    main()
