import hashlib
import json
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.camera_models import AssignmentInput, put_assignment
from app.db.model_eligibility import eligible_model_version
from app.db.models import ModelVerification, ModelVersion, PlatformAuditLog, User, utcnow
from app.scripts.model_artifact_verifier import verify_and_promote, verify_artifact
from tests.test_camera_models import seed_camera
from app.db.models import Organization, OrganizationMembership

PROMOTE = 'public.promote_verified_model(text,text,text,text,text,timestamptz,timestamptz)'
REVOKE = 'public.revoke_verified_model(text)'
ARTIFACT = b'synthetic model artifact for checksum testing'
LINUX = pytest.mark.skipif(os.open not in os.supports_dir_fd, reason='Secure mount reader requires POSIX dir_fd')


def model_version():
    return ModelVersion(
        id=str(uuid4()), model_key='security-' + uuid4().hex, version='1',
        artifact_ref='approved/releases/model.bin', artifact_sha256=hashlib.sha256(ARTIFACT).hexdigest(),
    )


def release(root, model, signer, *, payload=ARTIFACT, issued_at=None, signature_signer=None, **overrides):
    artifact = root / model.artifact_ref
    artifact.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        artifact.write_bytes(payload)
    issued = issued_at or utcnow() - timedelta(seconds=1)
    manifest = {
        'model_version_id': model.id, 'model_key': model.model_key, 'version': model.version,
        'artifact_ref': model.artifact_ref, 'artifact_sha256': model.artifact_sha256,
        'release_id': 'synthetic-release', 'issued_at': issued.isoformat(),
        'expires_at': (issued + timedelta(hours=1)).isoformat(),
    }
    encoded = json.dumps(manifest | overrides).encode()
    artifact.with_suffix('.bin.manifest.json').write_bytes(encoded)
    artifact.with_suffix('.bin.manifest.sig').write_bytes((signature_signer or signer).sign(encoded))
    return artifact


@LINUX
@pytest.mark.parametrize('defect', ['missing', 'wrong-digest', 'tampered', 'wrong-key', 'wrong-binding', 'expired', 'symlink'])
def test_signed_artifact_rejects_invalid_evidence(tmp_path, defect):
    signer = Ed25519PrivateKey.generate()
    model = model_version()
    if defect == 'wrong-digest':
        model.artifact_sha256 = '0' * 64
    artifact = release(
        tmp_path, model, signer, payload=None if defect == 'missing' else ARTIFACT,
        issued_at=utcnow() - timedelta(hours=2) if defect == 'expired' else None,
        signature_signer=Ed25519PrivateKey.generate() if defect == 'wrong-key' else None,
        **({'model_version_id': str(uuid4())} if defect == 'wrong-binding' else {}),
    )
    if defect == 'tampered':
        artifact.write_bytes(ARTIFACT + b' changed')
    if defect == 'symlink':
        artifact.rename(artifact.with_suffix('.real'))
        artifact.symlink_to(artifact.with_suffix('.real'))
    with pytest.raises((OSError, ValueError)):
        verify_artifact(tmp_path, 'approved', signer.public_key().public_bytes_raw(), model, 1024)


def role_connections(admin):
    """Use independent test logins. The owner connection provisions only this disposable DB."""
    roles = {}
    with admin.begin() as db:
        db.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ppe_model_verifier') THEN
                    CREATE ROLE ppe_model_verifier NOLOGIN;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ppe_model_revoker') THEN
                    CREATE ROLE ppe_model_revoker NOLOGIN;
                END IF;
            END $$
        """))
        db.exec_driver_sql(f'GRANT EXECUTE ON FUNCTION {PROMOTE} TO ppe_model_verifier')
        db.exec_driver_sql(f'GRANT EXECUTE ON FUNCTION {REVOKE} TO ppe_model_revoker')
        for label in ('publisher', 'runtime', 'verifier', 'revoker'):
            role, password = 'review_' + uuid4().hex, uuid4().hex
            db.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
            roles[label] = create_engine(admin.url.set(username=role, password=password))
            if label in ('publisher', 'verifier', 'runtime'):
                db.exec_driver_sql(f'GRANT SELECT ON model_versions, eligible_model_versions TO {role}')
            if label == 'runtime':
                db.exec_driver_sql(f'GRANT SELECT ON users, sites, organization_memberships, camera_model_assignments, cameras TO {role}')
                db.exec_driver_sql(f'GRANT INSERT, UPDATE, DELETE ON camera_model_assignments TO {role}')
                db.exec_driver_sql(f'GRANT UPDATE(model_revision) ON cameras TO {role}')
                db.exec_driver_sql(f'GRANT INSERT ON camera_model_history, audit_logs TO {role}')
            if label in ('verifier', 'revoker'):
                db.exec_driver_sql(f'GRANT ppe_model_{label} TO {role}')
    return roles


def direct_promotion(db, model, *, ref=None, digest=None, issued=None, expiry=None, manifest=None):
    return db.scalar(text("""
        SELECT public.promote_verified_model(:id,:ref,:digest,:manifest,:signer,:issued,:expiry)
    """), {
        'id': model.id, 'ref': ref or model.artifact_ref, 'digest': digest or model.artifact_sha256,
        'manifest': manifest or uuid4().hex * 2, 'signer': '0' * 64,
        'issued': issued or utcnow() - timedelta(seconds=1),
        'expiry': expiry or utcnow() + timedelta(hours=1),
    })


@LINUX
def test_postgres_verified_eligibility_boundaries_and_atomicity(tmp_path):
    url = os.environ.get('PPE_DISPOSABLE_POSTGRES_URL')
    if not url:
        pytest.skip('Set PPE_DISPOSABLE_POSTGRES_URL to a migrated disposable test database')
    owner = create_engine(url, hide_parameters=True)
    assert owner.dialect.name == 'postgresql'
    issuer = Ed25519PrivateKey.generate()
    key = issuer.public_key().public_bytes_raw()
    model = model_version()
    roles = {}
    try:
        roles = role_connections(owner)
        with Session(owner, expire_on_commit=False) as db, db.begin():
            org = Organization(name='Eligibility test')
            user = User(email=f'{uuid4()}@example.invalid', password_hash='unused')
            db.add_all([org, user, model])
            db.flush()
            db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role='admin'))
            camera = seed_camera(db, org.id)
        assignment = AssignmentInput(model_version_id=UUID(model.id), expected_revision=0)

        def assign(expected, revision=0):
            with Session(roles['runtime']) as db:
                actor = db.get(User, user.id)
                body = assignment.model_copy(update={'expected_revision': revision})
                if expected == 200:
                    assert put_assignment(org.id, UUID(camera), body, actor, db).model_version.id == model.id
                else:
                    with pytest.raises(HTTPException) as error:
                        put_assignment(org.id, UUID(camera), body, actor, db)
                    assert error.value.status_code == expected

        assign(404)
        with Session(roles['runtime']) as db, pytest.raises(DBAPIError):
            db.execute(text("UPDATE model_versions SET inference_eligible=true WHERE id=:id"), {'id': model.id})
        with Session(roles['runtime']) as db, pytest.raises(DBAPIError):
            db.execute(text("INSERT INTO camera_model_assignments VALUES (:camera,:model,now())"),
                       {'camera': camera, 'model': model.id})
        for role in ('publisher', 'runtime'):
            with Session(roles[role]) as db, pytest.raises(DBAPIError):
                direct_promotion(db, model)
            with Session(roles[role]) as db, pytest.raises(DBAPIError):
                db.execute(text('UPDATE model_verifications SET expires_at=now()'))

        for inputs in ({'ref': 'approved/other'}, {'digest': 'c' * 64},
                       {'expiry': utcnow() - timedelta(seconds=1)}):
            with Session(roles['verifier']) as db, pytest.raises(DBAPIError):
                direct_promotion(db, model, **inputs)
        with Session(roles['verifier']) as db, pytest.raises(FileNotFoundError):
            verify_and_promote(db, model.id, tmp_path, 'approved', key, 1024)

        artifact = release(tmp_path, model, issuer, payload=b'wrong bytes')
        with Session(roles['verifier']) as db, pytest.raises(ValueError, match='digest'):
            verify_and_promote(db, model.id, tmp_path, 'approved', key, 1024)
        assert artifact.read_bytes() != ARTIFACT
        release(tmp_path, model, issuer)
        with Session(roles['publisher']) as db, pytest.raises(DBAPIError):
            verify_and_promote(db, model.id, tmp_path, 'approved', key, 1024)

        # A database constraint rejects only this synthetic model's promotion audit.
        name = 'audit_failure_' + uuid4().hex
        with owner.begin() as db:
            db.exec_driver_sql(f"ALTER TABLE platform_audit_logs ADD CONSTRAINT {name} "
                               f"CHECK (target_id <> '{model.id}') NOT VALID")
        try:
            with pytest.raises(DBAPIError), Session(roles['verifier']) as db, db.begin():
                verify_and_promote(db, model.id, tmp_path, 'approved', key, 1024)
                db.flush()
            with Session(owner) as db:
                assert db.scalar(select(func.count()).select_from(ModelVerification).where(
                    ModelVerification.model_version_id == model.id,
                )) == 0
                assert db.scalar(select(func.count()).select_from(PlatformAuditLog).where(
                    PlatformAuditLog.target_id == model.id,
                )) == 0
            assign(404)
        finally:
            with owner.begin() as db:
                db.exec_driver_sql(f'ALTER TABLE platform_audit_logs DROP CONSTRAINT {name}')

        with Session(roles['verifier']) as db, db.begin():
            evidence = verify_and_promote(db, model.id, tmp_path, 'approved', key, 1024)
        with Session(owner) as db:
            record = db.get(ModelVerification, evidence)
            assert record.artifact_ref == model.artifact_ref
            assert record.artifact_sha256 == model.artifact_sha256
            assert record.verifier == roles['verifier'].url.username
            assert db.scalar(select(PlatformAuditLog.action).where(
                PlatformAuditLog.target_id == model.id,
            )) == 'model_version.verify_promote'
            with pytest.raises(DBAPIError):
                db.execute(text('UPDATE model_verifications SET expires_at=now() WHERE id=:id'), {'id': evidence})
            db.rollback()
        assign(200)

        with Session(roles['publisher']) as db, pytest.raises(DBAPIError):
            db.scalar(text('SELECT public.revoke_verified_model(:id)'), {'id': model.id})
        with Session(roles['revoker']) as db, db.begin():
            assert db.scalar(text('SELECT public.revoke_verified_model(:id)'), {'id': model.id}) == evidence
        assign(404, revision=1)
        with Session(roles['verifier']) as db, pytest.raises(DBAPIError):
            verify_and_promote(db, model.id, tmp_path, 'approved', key, 1024)
        with Session(roles['runtime']) as db:
            assert db.scalar(select(ModelVersion.id).where(
                ModelVersion.id == model.id, eligible_model_version(db),
            )) is None
        with Session(owner) as db:
            assert db.scalar(text('SELECT model_version_id FROM camera_model_assignments WHERE camera_id=:id'),
                             {'id': camera}) == model.id
            assert db.scalar(select(func.count()).select_from(PlatformAuditLog).where(
                PlatformAuditLog.target_id == model.id,
            )) == 2
    finally:
        for connection in roles.values():
            connection.dispose()
        owner.dispose()
