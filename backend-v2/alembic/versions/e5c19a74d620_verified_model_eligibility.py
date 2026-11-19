"""Require immutable verified artifact evidence for model eligibility."""

from alembic import op
import sqlalchemy as sa

revision = 'e5c19a74d620'
down_revision = 'd2f4a193b0c7'
branch_labels = None
depends_on = None

PROMOTE = 'public.promote_verified_model(text,text,text,text,text,timestamptz,timestamptz)'
REVOKE = 'public.revoke_verified_model(text)'


def upgrade():
    op.create_table(
        'model_verifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('model_version_id', sa.String(36), sa.ForeignKey('model_versions.id'), nullable=False),
        sa.Column('artifact_ref', sa.String(500), nullable=False),
        sa.Column('artifact_sha256', sa.String(64), nullable=False),
        sa.Column('manifest_sha256', sa.String(64), nullable=False),
        sa.Column('signer_key_sha256', sa.String(64), nullable=False),
        sa.Column('verifier', sa.String(255), nullable=False),
        sa.Column('manifest_issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('model_version_id', 'manifest_sha256', name='uq_verification_manifest'),
        sa.CheckConstraint('expires_at > verified_at', name='valid_expiry'),
    )
    op.create_index(op.f('ix_model_verifications_model_version_id'), 'model_verifications', ['model_version_id'])
    op.create_table(
        'model_verification_revocations',
        sa.Column('verification_id', sa.Integer(), sa.ForeignKey('model_verifications.id'), primary_key=True),
        sa.Column('actor', sa.String(255), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
        CREATE FUNCTION public.reject_verification_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
        BEGIN
            RAISE EXCEPTION 'Model verification records are append-only' USING ERRCODE = 'check_violation';
        END;
        $$
    """)
    for table in ('model_verifications', 'model_verification_revocations'):
        op.execute(f"""
            CREATE TRIGGER verification_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE ON public.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION public.reject_verification_mutation()
        """)
    op.execute("""
        CREATE FUNCTION public.promote_verified_model(
            model_id text, verified_ref text, verified_digest text,
            manifest_digest text, signer_digest text, manifest_issued timestamptz,
            verified_until timestamptz
        ) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
        DECLARE
            recorded_id integer;
            verified_time timestamptz;
        BEGIN
            IF pg_has_role(session_user, to_regrole('ppe_model_verifier'), 'MEMBER')
               IS DISTINCT FROM true THEN
                RAISE EXCEPTION 'Verifier role required' USING ERRCODE = 'insufficient_privilege';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('ppe:model-eligibility:' || model_id, 0));
            verified_time := clock_timestamp();
            IF manifest_issued IS NULL OR manifest_issued > verified_time
                OR verified_until IS NULL OR verified_until <= verified_time
                OR verified_until > manifest_issued + interval '24 hours'
                OR verified_until > verified_time + interval '24 hours'
                OR (manifest_digest ~ '^[0-9a-f]{64}$') IS DISTINCT FROM true
                OR (signer_digest ~ '^[0-9a-f]{64}$') IS DISTINCT FROM true
                OR (verified_digest ~ '^[0-9a-f]{64}$') IS DISTINCT FROM true THEN
                RAISE EXCEPTION 'Invalid or stale verification evidence' USING ERRCODE = 'check_violation';
            END IF;

            IF EXISTS (
                SELECT 1 FROM public.model_verifications v
                WHERE v.model_version_id = model_id AND v.manifest_issued_at >= manifest_issued
            ) THEN
                RAISE EXCEPTION 'Evidence is not newer than the last verification' USING ERRCODE = 'check_violation';
            END IF;
            IF EXISTS (
                SELECT 1 FROM public.model_verification_revocations r
                JOIN public.model_verifications v ON v.id = r.verification_id
                WHERE v.model_version_id = model_id AND r.revoked_at >= manifest_issued
            ) THEN
                RAISE EXCEPTION 'Evidence predates revocation' USING ERRCODE = 'check_violation';
            END IF;

            INSERT INTO public.model_verifications
                (model_version_id, artifact_ref, artifact_sha256, manifest_sha256,
                 signer_key_sha256, verifier, manifest_issued_at, verified_at, expires_at)
            SELECT id, artifact_ref, artifact_sha256, manifest_digest,
                   signer_digest, session_user, manifest_issued, verified_time, verified_until
            FROM public.model_versions
            WHERE id = model_id AND artifact_ref = verified_ref AND artifact_sha256 = verified_digest
            RETURNING id INTO recorded_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Verification evidence does not match registry' USING ERRCODE = 'check_violation';
            END IF;

            INSERT INTO public.platform_audit_logs (id, actor, action, target_id, details, created_at)
            VALUES (gen_random_uuid()::text, session_user, 'model_version.verify_promote', model_id,
                    json_build_object('verification_id', recorded_id), verified_time);
            RETURN recorded_id;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION public.revoke_verified_model(model_id text) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
        DECLARE
            latest_id integer;
            revoked_id integer;
            revoked_time timestamptz;
        BEGIN
            IF pg_has_role(session_user, to_regrole('ppe_model_revoker'), 'MEMBER')
               IS DISTINCT FROM true THEN
                RAISE EXCEPTION 'Revoker role required' USING ERRCODE = 'insufficient_privilege';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('ppe:model-eligibility:' || model_id, 0));
            SELECT max(id) INTO latest_id FROM public.model_verifications WHERE model_version_id = model_id;
            IF latest_id IS NULL THEN
                RETURN NULL;
            END IF;
            revoked_time := clock_timestamp();
            INSERT INTO public.model_verification_revocations (verification_id, actor, revoked_at)
            VALUES (latest_id, session_user, revoked_time)
            ON CONFLICT (verification_id) DO NOTHING RETURNING verification_id INTO revoked_id;
            IF revoked_id IS NOT NULL THEN
                INSERT INTO public.platform_audit_logs (id, actor, action, target_id, details, created_at)
                VALUES (gen_random_uuid()::text, session_user, 'model_version.revoke', model_id,
                        json_build_object('verification_id', revoked_id), revoked_time);
            END IF;
            RETURN revoked_id;
        END;
        $$
    """)
    op.execute(f'REVOKE ALL ON FUNCTION {PROMOTE}, {REVOKE} FROM PUBLIC')
    op.execute('REVOKE ALL ON TABLE public.model_verifications, public.model_verification_revocations FROM PUBLIC')
    op.execute("""
        CREATE VIEW public.eligible_model_versions AS
        SELECT m.id AS model_version_id
        FROM public.model_versions m
        JOIN public.model_verifications v ON v.id = (
            SELECT max(candidate.id) FROM public.model_verifications candidate
            WHERE candidate.model_version_id = m.id
        )
        WHERE v.artifact_ref = m.artifact_ref AND v.artifact_sha256 = m.artifact_sha256
            AND v.expires_at > clock_timestamp()
            AND NOT EXISTS (
                SELECT 1 FROM public.model_verification_revocations r WHERE r.verification_id = v.id
            )
    """)
    op.execute("""
        CREATE FUNCTION public.guard_camera_model_assignment() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('ppe:model-eligibility:' || NEW.model_version_id, 0));
            IF NOT EXISTS (
                SELECT 1 FROM public.eligible_model_versions WHERE model_version_id = NEW.model_version_id
            ) THEN
                RAISE EXCEPTION 'Camera model requires current verification evidence'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER camera_model_verified
        BEFORE INSERT OR UPDATE OF model_version_id ON public.camera_model_assignments
        FOR EACH ROW EXECUTE FUNCTION public.guard_camera_model_assignment()
    """)
    op.drop_column('model_versions', 'inference_eligible')


def downgrade():
    op.add_column('model_versions', sa.Column('inference_eligible', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute(f'DROP FUNCTION {PROMOTE}, {REVOKE}')
    op.execute('DROP TRIGGER camera_model_verified ON public.camera_model_assignments')
    op.execute('DROP FUNCTION public.guard_camera_model_assignment()')
    op.execute('DROP VIEW public.eligible_model_versions')
    op.drop_table('model_verification_revocations')
    op.drop_table('model_verifications')
    op.execute('DROP FUNCTION public.reject_verification_mutation()')
