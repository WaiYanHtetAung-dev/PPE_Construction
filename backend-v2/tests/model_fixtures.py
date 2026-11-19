from datetime import timedelta
from uuid import uuid4

from app.db.models import ModelVerification, utcnow


def seed_verified_model(db, model):
    """Populate trusted synthetic evidence in tests unrelated to artifact verification."""
    now = utcnow()
    db.add(ModelVerification(
        model_version_id=model.id, artifact_ref=model.artifact_ref,
        artifact_sha256=model.artifact_sha256, manifest_sha256=uuid4().hex * 2,
        signer_key_sha256='f' * 64, verifier='synthetic-test',
        manifest_issued_at=now, verified_at=now, expires_at=now + timedelta(hours=1),
    ))
    db.flush()
