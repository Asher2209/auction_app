"""chain ids and block numbers as 64-bit integers

Revision ID: r28bigints01
Revises: q27schemaalign01
Create Date: 2026-10-26 00:00:00.000000

A 32-bit INTEGER cannot hold every chain id (the local test chain's is 131277322940537) and would one day run out of
block numbers. SQLite integers are always 64-bit, so SQLite is left alone; PostgreSQL and MySQL get BIGINT, which only
widens the column and keeps every value.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r28bigints01'
down_revision = 'q27schemaalign01'
branch_labels = None
depends_on = None

COLUMNS = (('crypto_payments', 'chain_id'), ('crypto_payments', 'block_number'),
           ('blockchain_assets', 'mint_block_number'),
           ('blockchain_transfers', 'block_number'), ('blockchain_transfers', 'chain_id'))


def upgrade():
    if op.get_bind().dialect.name == 'sqlite':
        return
    for table, column in COLUMNS:
        op.alter_column(table, column, existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True)


def downgrade():
    if op.get_bind().dialect.name == 'sqlite':
        return
    for table, column in COLUMNS:  # fails, rightly, if a value no longer fits
        op.alter_column(table, column, existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True)
