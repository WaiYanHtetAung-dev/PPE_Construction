"""Persist incident outbox retry state."""

import sqlalchemy as sa
from alembic import op

revision = 'c38f0a72e914'
down_revision = '81c540a1d2f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('incident_outbox', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('incident_outbox', sa.Column('retry_at', sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column('incident_outbox', 'retry_at')
    op.drop_column('incident_outbox', 'attempts')
