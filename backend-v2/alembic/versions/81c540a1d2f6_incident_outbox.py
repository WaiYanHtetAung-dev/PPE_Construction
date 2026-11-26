"""Add the incident outbox and idempotency record."""

import sqlalchemy as sa
from alembic import op

revision = '81c540a1d2f6'
down_revision = 'e5c19a74d620'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'incident_outbox',
        sa.Column('event_id', sa.String(36), primary_key=True),
        sa.Column('incident_id', sa.String(36), sa.ForeignKey('incidents.id'), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table('incident_outbox')
