"""record whether a rejected card may be resubmitted

Revision ID: g17resubmission01
Revises: e16f3tradingcards
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g17resubmission01'
down_revision = 'e16f3tradingcards'
branch_labels = None
depends_on = None


def upgrade():
    # existing rows keep today's behaviour: a rejected card can be edited and resubmitted
    with op.batch_alter_table('collectible_verifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resubmission_allowed', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('collectible_verifications', schema=None) as batch_op:
        batch_op.drop_column('resubmission_allowed')
