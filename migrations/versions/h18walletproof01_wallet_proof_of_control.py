"""wallets are linked by proving control: verification time, one account per wallet, drop payout_wallet

Revision ID: h18walletproof01
Revises: g17resubmission01
Create Date: 2026-10-07 00:00:00.000000

Existing wallet addresses stay, but count as unverified until their owner signs the challenge once.
Two accounts holding the same address must be resolved before upgrading, or the unique constraint fails.
payout_wallet is no longer read anywhere (the card flow pays the token owner), so it is dropped.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h18walletproof01'
down_revision = 'g17resubmission01'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wallet_verified_at', sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint('uq_users_wallet_address', ['wallet_address'])
        batch_op.drop_column('payout_wallet')


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payout_wallet', sa.String(length=42), nullable=True))
        batch_op.drop_constraint('uq_users_wallet_address', type_='unique')
        batch_op.drop_column('wallet_verified_at')
