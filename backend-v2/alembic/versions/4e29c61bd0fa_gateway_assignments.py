"""Persist scoped gateway credentials and expose the read-only assignment projection."""

import sqlalchemy as sa
from alembic import op

revision = '4e29c61bd0fa'
down_revision = 'c38f0a72e914'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('gateway_principals',
                    sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id'), nullable=False),
                    sa.Column('disabled_at', sa.DateTime(timezone=True)))
    op.create_table('gateway_camera_scopes',
                    sa.Column('principal_id', sa.String(36), sa.ForeignKey('gateway_principals.id'), primary_key=True),
                    sa.Column('camera_id', sa.String(36), sa.ForeignKey('cameras.id', ondelete='CASCADE'), primary_key=True),
                    sa.Column('site_id', sa.String(36), sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False))
    op.create_table('gateway_credentials',
                    sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('principal_id', sa.String(36), sa.ForeignKey('gateway_principals.id'), nullable=False),
                    sa.Column('audience', sa.String(64), nullable=False),
                    sa.Column('secret_sha256', sa.String(64), nullable=False),
                    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
                    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
                    sa.Column('revoked_at', sa.DateTime(timezone=True)),
                    sa.CheckConstraint('expires_at > issued_at', name='valid_expiry'))
    op.create_index('ix_gateway_credentials_principal_id', 'gateway_credentials', ['principal_id'])
    op.execute('''
        CREATE VIEW public.gateway_snapshot_credentials AS
        SELECT k.id, k.principal_id, k.audience, k.secret_sha256, k.expires_at
        FROM public.gateway_credentials k
        JOIN public.gateway_principals p ON p.id = k.principal_id
        WHERE p.disabled_at IS NULL AND k.revoked_at IS NULL
          AND k.issued_at <= statement_timestamp() AND k.expires_at > statement_timestamp()
    ''')
    op.execute('''
        CREATE VIEW public.gateway_snapshot_assignments AS
        SELECT p.id AS principal_id, p.organization_id, s.id AS site_id,
               c.id AS camera_id, c.model_revision, c.enabled,
               m.id AS model_version_id, m.model_key, m.version, m.class_map,
               evidence.latest AS verification_generation, evidence.floor AS revoked_through_generation,
               v.expires_at AS evidence_expiry, eligible.model_version_id IS NOT NULL AS eligible
        FROM public.gateway_camera_scopes scope
        JOIN public.gateway_principals p ON p.id = scope.principal_id
        JOIN public.cameras c ON c.id = scope.camera_id AND c.site_id = scope.site_id
        JOIN public.sites s ON s.id = c.site_id AND s.organization_id = p.organization_id
        LEFT JOIN public.camera_model_assignments a ON a.camera_id = c.id
        LEFT JOIN public.model_versions m ON m.id = a.model_version_id
        LEFT JOIN LATERAL (
            SELECT max(e.id) AS latest, max(r.verification_id) AS floor
            FROM public.model_verifications e
            LEFT JOIN public.model_verification_revocations r ON r.verification_id = e.id
            WHERE e.model_version_id = m.id
        ) evidence ON true
        LEFT JOIN public.model_verifications v ON v.id = evidence.latest
        LEFT JOIN public.eligible_model_versions eligible ON eligible.model_version_id = m.id
        WHERE p.disabled_at IS NULL
    ''')
    op.execute('REVOKE ALL ON public.gateway_snapshot_credentials, public.gateway_snapshot_assignments FROM PUBLIC')
    op.execute('REVOKE ALL ON public.gateway_credentials, public.gateway_principals, public.gateway_camera_scopes FROM PUBLIC')


def downgrade():
    op.execute('DROP VIEW public.gateway_snapshot_assignments')
    op.execute('DROP VIEW public.gateway_snapshot_credentials')
    op.drop_table('gateway_credentials')
    op.drop_table('gateway_camera_scopes')
    op.drop_table('gateway_principals')
