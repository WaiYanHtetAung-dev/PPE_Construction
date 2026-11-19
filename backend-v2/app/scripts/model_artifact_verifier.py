"""Verify signed model artifacts as an independent Linux workload."""

import argparse
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from app.db.models import ModelVersion
from app.db.session import SessionLocal
from app.model_artifact_integrity import check_artifact


def verify_artifact(root, namespace, public_key, model, max_bytes):
    checked = check_artifact(root, namespace, public_key, model, max_bytes)
    return checked.manifest, checked.manifest_sha256, checked.signer_key_sha256


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
