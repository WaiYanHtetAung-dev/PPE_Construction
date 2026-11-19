"""Verify signed model artifacts as an independent Linux workload."""

import argparse
import hashlib
import hmac
import os
import stat
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app.db.models import ModelVersion, utcnow
from app.db.session import SessionLocal
from app.model_artifacts import within_namespace


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    model_version_id: UUID
    model_key: str
    version: str
    artifact_ref: str
    artifact_sha256: str
    release_id: Annotated[str, Field(min_length=1, max_length=128)]
    issued_at: AwareDatetime
    expires_at: AwareDatetime


@contextmanager
def open_artifact(root: Path, key: str):
    # The mount root and its parents are provisioned by the operator.
    with ExitStack() as stack:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(root, flags)
        stack.callback(os.close, directory)
        *parents, filename = key.split('/')
        for part in parents:
            directory = os.open(part, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Artifact entry must be a regular file')
            yield stream


def read_small(root: Path, key: str, limit: int) -> bytes:
    with open_artifact(root, key) as stream:
        result = stream.read(limit + 1)
    if len(result) > limit:
        raise ValueError('Artifact metadata exceeds size limit')
    return result


def verify_artifact(root: Path, namespace: str, public_key: bytes, model: ModelVersion,
                    max_bytes: int) -> tuple[Manifest, str, str]:
    key = model.artifact_ref
    if not within_namespace(key, namespace) or max_bytes < 1:
        raise ValueError('Artifact namespace or size limit invalid')
    payload = read_small(root, key + '.manifest.json', 65536)
    signature = read_small(root, key + '.manifest.sig', 64)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except InvalidSignature:
        raise ValueError('Manifest signature invalid') from None
    manifest = Manifest.model_validate_json(payload)
    now = utcnow()
    if not manifest.issued_at <= now < manifest.expires_at <= manifest.issued_at + timedelta(hours=24):
        raise ValueError('Manifest is stale or outside the permitted validity window')
    if (str(manifest.model_version_id), manifest.model_key, manifest.version,
        manifest.artifact_ref, manifest.artifact_sha256) != (
        model.id, model.model_key, model.version, key, model.artifact_sha256,
    ):
        raise ValueError('Manifest does not match registered model')
    digest = hashlib.sha256()
    count = 0
    with open_artifact(root, key) as artifact:
        while chunk := artifact.read(min(1024 * 1024, max_bytes - count + 1)):
            count += len(chunk)
            if count > max_bytes:
                raise ValueError('Artifact exceeds size limit')
            digest.update(chunk)
    if not count or not hmac.compare_digest(digest.hexdigest(), model.artifact_sha256):
        raise ValueError('Artifact digest mismatch')
    return manifest, hashlib.sha256(payload).hexdigest(), hashlib.sha256(public_key).hexdigest()


def verify_and_promote(db, model_id, root, namespace, public_key, max_bytes):
    model = db.scalar(select(ModelVersion).where(ModelVersion.id == model_id))
    if model is None:
        raise ValueError('Model version not found')
    manifest, manifest_digest, signer_digest = verify_artifact(
        root, namespace, public_key, model, max_bytes,
    )
    return db.scalar(text("""
        SELECT public.promote_verified_model(
            :model_id, :artifact_ref, :artifact_digest, :manifest_digest, :signer_digest,
            :issued_at, :expires_at
        )
    """), {
        'model_id': model.id, 'artifact_ref': model.artifact_ref,
        'artifact_digest': model.artifact_sha256, 'manifest_digest': manifest_digest,
        'signer_digest': signer_digest, 'issued_at': manifest.issued_at,
        'expires_at': manifest.expires_at,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify-promote', 'revoke'])
    parser.add_argument('model_version_id', type=UUID)
    args = parser.parse_args()
    try:
        with SessionLocal.begin() as db:
            if db.get_bind().dialect.name != 'postgresql':
                raise ValueError('Model verification requires PostgreSQL')
            if args.action == 'revoke':
                db.scalar(text('SELECT public.revoke_verified_model(:id)'), {'id': str(args.model_version_id)})
            else:
                root = Path(os.environ['MODEL_VERIFIER_ARTIFACT_ROOT'])
                if not root.is_absolute() or not os.statvfs(root).f_flag & os.ST_RDONLY:
                    raise ValueError('Artifact root must be on a read-only mount')
                with Path(os.environ['MODEL_VERIFIER_PUBLIC_KEY']).open('rb') as keyfile:
                    public_key = keyfile.read(33)
                verify_and_promote(
                    db, str(args.model_version_id), root, os.environ['MODEL_ARTIFACT_NAMESPACE'],
                    public_key, int(os.environ['MODEL_VERIFIER_MAX_BYTES']),
                )
    except Exception:
        parser.exit(1, 'Artifact operation failed. No changes were committed.\n')
    print('Artifact operation completed.')


if __name__ == '__main__':
    main()
