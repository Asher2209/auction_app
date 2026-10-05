"""add payout_wallet to user

Revision ID: c15e5seller01
Revises: b15d3tails02
Create Date: 2026-10-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c15e5seller01'
down_revision = 'b15d3tails02'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payout_wallet', sa.String(length=42), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('payout_wallet')
