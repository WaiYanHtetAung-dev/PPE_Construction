"""Track camera assignment revisions and append-only history."""

import sqlalchemy as sa
from alembic import op

revision = 'd2f4a193b0c7'
down_revision = 'a6c37b0e4f21'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cameras', sa.Column('model_revision', sa.BigInteger(), server_default='0', nullable=False))
    op.create_table(
        'camera_model_history',
        sa.Column('camera_id', sa.String(36), sa.ForeignKey('cameras.id'), primary_key=True),
        sa.Column('revision', sa.BigInteger(), primary_key=True),
        sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('actor_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('previous_model_version_id', sa.String(36), sa.ForeignKey('model_versions.id')),
        sa.Column('model_version_id', sa.String(36), sa.ForeignKey('model_versions.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('revision > 0', name='positive_revision'),
    )
    op.execute("""
        CREATE FUNCTION reject_camera_model_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Camera model history is append-only' USING ERRCODE = 'check_violation';
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER camera_model_history_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON camera_model_history FOR EACH STATEMENT
        EXECUTE FUNCTION reject_camera_model_history_mutation()
    """)


def downgrade():
    op.drop_table('camera_model_history')
    op.execute('DROP FUNCTION reject_camera_model_history_mutation()')
    op.drop_column('cameras', 'model_revision')
