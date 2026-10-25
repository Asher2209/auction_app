"""worker leases: worker_leases (one background worker at a time)

Revision ID: p26leases01
Revises: o25onerole01
Create Date: 2026-10-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p26leases01'
down_revision = 'o25onerole01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'worker_leases',
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('holder', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('name'),
    )


def downgrade():
    op.drop_table('worker_leases')
