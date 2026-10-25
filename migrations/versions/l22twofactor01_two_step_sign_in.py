"""two-step sign-in: users.totp_secret, totp_enabled_at, totp_last_step, totp_recovery

Revision ID: l22twofactor01
Revises: k21emailverify01
Create Date: 2026-10-25 00:00:00.000000

Every column starts empty: two-step sign-in is off for everyone until they set it up from their account page.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l22twofactor01'
down_revision = 'k21emailverify01'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('totp_secret', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('totp_enabled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('totp_last_step', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('totp_recovery', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('users', 'totp_recovery')  # in place (SQLite 3.35+); a batch rebuild of users would break its foreign keys
    op.drop_column('users', 'totp_last_step')
    op.drop_column('users', 'totp_enabled_at')
    op.drop_column('users', 'totp_secret')
