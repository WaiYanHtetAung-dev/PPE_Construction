from sqlalchemy import column, func, select, table, text
from sqlalchemy.orm import Session

from app.db.models import ModelVerification, ModelVerificationRevocation, ModelVersion


eligible_versions = table('eligible_model_versions', column('model_version_id'), schema='public')


def eligible_model_version(db: Session):
    if db.get_bind().dialect.name == 'postgresql':
        return select(eligible_versions.c.model_version_id).where(
            eligible_versions.c.model_version_id == ModelVersion.id,
        ).correlate(ModelVersion).exists()
    latest = (
        select(func.max(ModelVerification.id))
        .where(ModelVerification.model_version_id == ModelVersion.id)
        .correlate(ModelVersion)
        .scalar_subquery()
    )
    return select(ModelVerification.id).where(
        ModelVerification.id == latest,
        ModelVerification.artifact_ref == ModelVersion.artifact_ref,
        ModelVerification.artifact_sha256 == ModelVersion.artifact_sha256,
        ModelVerification.expires_at > func.now(),
        ~select(ModelVerificationRevocation.verification_id).where(
            ModelVerificationRevocation.verification_id == ModelVerification.id,
        ).exists(),
    ).correlate(ModelVersion).exists()


def lock_model_eligibility(db: Session, model_id: str) -> None:
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended("
                        "'ppe:model-eligibility:' || :model_id, 0))"), {'model_id': model_id})
