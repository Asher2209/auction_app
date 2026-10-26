"""bidding features: reserve price, Buy It Now price, automatic (maximum) bids

Revision ID: s29biddingfeatures01
Revises: r28bigints01
Create Date: 2026-10-26 00:00:00.000000

Only additions: existing auctions have no reserve and no Buy It Now price, existing bids were all placed by hand.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's29biddingfeatures01'
down_revision = 'r28bigints01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('auctions', sa.Column('reserve_price', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('auctions', sa.Column('buy_now_price', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('bids', sa.Column('is_auto', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'max_bids',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('auction_id', sa.Integer(), nullable=False),
        sa.Column('buyer_id', sa.Integer(), nullable=False),
        sa.Column('max_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('set_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['auction_id'], ['auctions.id']),
        sa.ForeignKeyConstraint(['buyer_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('auction_id', 'buyer_id', name='uq_max_bid_auction_buyer'),
    )
    op.create_index('ix_max_bids_auction_id', 'max_bids', ['auction_id'])


def downgrade():
    op.drop_index('ix_max_bids_auction_id', table_name='max_bids')
    op.drop_table('max_bids')
    # in place (SQLite 3.35+): a batch rebuild of these tables would trip their foreign keys
    op.drop_column('bids', 'is_auto')
    op.drop_column('auctions', 'buy_now_price')
    op.drop_column('auctions', 'reserve_price')
