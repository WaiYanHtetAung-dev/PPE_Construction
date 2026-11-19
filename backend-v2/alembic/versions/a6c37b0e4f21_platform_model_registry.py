"""Add publisher grants, platform audit and model eligibility."""

import sqlalchemy as sa
from alembic import op

revision = 'a6c37b0e4f21'
down_revision = '9db36ad49c74'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_versions', sa.Column('inference_eligible', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'platform_publishers',
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table(
        'platform_audit_logs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('target_id', sa.String(36), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("""
        CREATE FUNCTION protect_model_version_metadata() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(NEW.id, NEW.model_key, NEW.version, NEW.artifact_ref,
                   NEW.artifact_sha256, NEW.class_map::jsonb)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.model_key, OLD.version, OLD.artifact_ref,
                   OLD.artifact_sha256, OLD.class_map::jsonb) THEN
                RAISE EXCEPTION 'Published model version metadata is immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER protect_model_version_metadata
        BEFORE UPDATE ON model_versions FOR EACH ROW
        EXECUTE FUNCTION protect_model_version_metadata()
    """)


def downgrade():
    op.execute('DROP TRIGGER protect_model_version_metadata ON model_versions')
    op.execute('DROP FUNCTION protect_model_version_metadata()')
    op.drop_table('platform_audit_logs')
    op.drop_table('platform_publishers')
    op.drop_column('model_versions', 'inference_eligible')
