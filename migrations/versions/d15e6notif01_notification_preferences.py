"""notification preferences for buyers

Revision ID: d15e6notif01
Revises: c15e5seller01
Create Date: 2026-10-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd15e6notif01'
down_revision = 'c15e5seller01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notification_preferences',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('notify_outbid', sa.Boolean(), nullable=False),
        sa.Column('notify_ending_soon', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('user_id')
    )


def downgrade():
    op.drop_table('notification_preferences')
