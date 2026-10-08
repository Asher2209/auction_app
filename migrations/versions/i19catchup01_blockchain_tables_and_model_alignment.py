"""catch up with the models: blockchain asset and transfer tables, platform card ID, card image URL, verification fixes

Revision ID: i19catchup01
Revises: h18walletproof01
Create Date: 2026-10-08 00:00:00.000000

Until now the card tables only existed in databases built with db.create_all(); a database built from these
migrations (MySQL) lacked them and differed from the models in ways that break real requests:
- blockchain_assets and blockchain_transfers did not exist, and collectible_cards had no platform_card_id.
- card_images had no url column, and path was NOT NULL although cards can use an external image URL.
- collectible_verifications required grader and certificate_number (ungraded cards have neither) and made
  certificate_number UNIQUE, so a second submission of the same certificate failed instead of being flagged
  for review. verified_by and photos_verified_by were strings although they hold the admin's user id.
- Several timestamp and flag columns were NOT NULL where the models allow NULL; they now match the models.

Assumes the database was built from this migration chain (MySQL names the old unnamed unique constraint
after its column, "certificate_number"). The leftover listing-details columns and tables from b15d3tails02
are nullable and unused, so they are left in place rather than dropped with their data.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i19catchup01'
down_revision = 'h18walletproof01'
branch_labels = None
depends_on = None

# (table, column, type) that become nullable to match the models
RELAXED = [
    ('card_images', 'path', sa.String(length=255)),
    ('card_images', 'uploaded_at', sa.DateTime()),
    ('card_types', 'is_active', sa.Boolean()),
    ('card_types', 'created_at', sa.DateTime()),
    ('card_types', 'updated_at', sa.DateTime()),
    ('card_verification_checklists', 'result', sa.String(length=20)),
    ('card_verification_checklists', 'created_at', sa.DateTime()),
    ('card_verification_checklists', 'updated_at', sa.DateTime()),
    ('card_verification_history', 'created_at', sa.DateTime()),
    ('collectible_cards', 'is_graded', sa.Boolean()),
    ('collectible_cards', 'language', sa.String(length=50)),
    ('collectible_cards', 'created_at', sa.DateTime()),
    ('collectible_cards', 'updated_at', sa.DateTime()),
    ('collectible_verifications', 'grader', sa.String(length=100)),
    ('collectible_verifications', 'certificate_number', sa.String(length=100)),
    ('collectible_verifications', 'is_graded', sa.Boolean()),
    ('collectible_verifications', 'verification_status', sa.String(length=50)),
    ('collectible_verifications', 'photos_verified', sa.Boolean()),
    ('collectible_verifications', 'duplicate_flag', sa.Boolean()),
    ('collectible_verifications', 'submission_count', sa.Integer()),
    ('collectible_verifications', 'created_at', sa.DateTime()),
    ('collectible_verifications', 'updated_at', sa.DateTime()),
    ('supported_graders', 'is_active', sa.Boolean()),
    ('supported_graders', 'api_key_required', sa.Boolean()),
    ('supported_graders', 'created_at', sa.DateTime()),
    ('supported_graders', 'updated_at', sa.DateTime()),
    ('verification_logs', 'timestamp', sa.DateTime()),
]


def upgrade():
    with op.batch_alter_table('collectible_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform_card_id', sa.String(length=20), nullable=True))
        batch_op.create_index('ix_collectible_cards_platform_card_id', ['platform_card_id'], unique=True)

    with op.batch_alter_table('card_images', schema=None) as batch_op:
        batch_op.add_column(sa.Column('url', sa.String(length=500), nullable=True))

    # The old UNIQUE(certificate_number) was created without a name. MySQL names it after the column; SQLite leaves
    # it unnamed, and batch mode then needs a naming convention to address it. Ask the database which it is.
    unique_name = next((uc['name'] for uc in sa.inspect(op.get_bind()).get_unique_constraints('collectible_verifications')
                        if uc['column_names'] == ['certificate_number']), 'certificate_number')
    batch_kw = {}
    if unique_name is None:
        unique_name = 'uq_collectible_verifications_certificate_number'
        batch_kw = {'naming_convention': {'uq': 'uq_%(table_name)s_%(column_0_name)s'}}
    with op.batch_alter_table('collectible_verifications', schema=None, **batch_kw) as batch_op:
        batch_op.drop_constraint(unique_name, type_='unique')  # duplicates are flagged, not refused
        batch_op.alter_column('verified_by', existing_type=sa.String(length=100), type_=sa.Integer(), existing_nullable=True)
        batch_op.alter_column('photos_verified_by', existing_type=sa.String(length=100), type_=sa.Integer(), existing_nullable=True)
        batch_op.create_foreign_key('fk_collectible_verifications_verified_by_users', 'users', ['verified_by'], ['id'])
        batch_op.create_foreign_key('fk_collectible_verifications_photos_verified_by_users', 'users', ['photos_verified_by'], ['id'])

    for table, column, type_ in RELAXED:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(column, existing_type=type_, nullable=True)

    op.create_table(
        'blockchain_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collectible_card_id', sa.Integer(), nullable=False),
        sa.Column('token_id', sa.Integer(), nullable=True),
        sa.Column('contract_address', sa.String(length=42), nullable=False),
        sa.Column('blockchain_network', sa.String(length=30), nullable=False),
        sa.Column('owner_wallet', sa.String(length=42), nullable=False),
        sa.Column('previous_owner', sa.String(length=42), nullable=True),
        sa.Column('metadata_hash', sa.String(length=66), nullable=True),
        sa.Column('token_uri', sa.String(length=500), nullable=True),
        sa.Column('mint_transaction_hash', sa.String(length=66), nullable=True),
        sa.Column('mint_block_number', sa.Integer(), nullable=True),
        sa.Column('mint_date', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['collectible_card_id'], ['collectible_cards.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('collectible_card_id'),
    )
    with op.batch_alter_table('blockchain_assets', schema=None) as batch_op:
        batch_op.create_index('ix_blockchain_assets_token_id', ['token_id'], unique=True)
        batch_op.create_index('ix_blockchain_assets_owner_wallet', ['owner_wallet'], unique=False)
        batch_op.create_index('ix_blockchain_assets_mint_transaction_hash', ['mint_transaction_hash'], unique=True)

    op.create_table(
        'blockchain_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('blockchain_asset_id', sa.Integer(), nullable=False),
        sa.Column('from_wallet', sa.String(length=42), nullable=False),
        sa.Column('to_wallet', sa.String(length=42), nullable=False),
        sa.Column('auction_id', sa.Integer(), nullable=True),
        sa.Column('transaction_hash', sa.String(length=66), nullable=True),
        sa.Column('block_number', sa.Integer(), nullable=True),
        sa.Column('chain_id', sa.Integer(), nullable=True),
        sa.Column('network', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['blockchain_asset_id'], ['blockchain_assets.id'], ),
        sa.ForeignKeyConstraint(['auction_id'], ['auctions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('blockchain_transfers', schema=None) as batch_op:
        batch_op.create_index('ix_blockchain_transfers_from_wallet', ['from_wallet'], unique=False)
        batch_op.create_index('ix_blockchain_transfers_to_wallet', ['to_wallet'], unique=False)
        batch_op.create_index('ix_blockchain_transfers_transaction_hash', ['transaction_hash'], unique=True)


def downgrade():
    with op.batch_alter_table('blockchain_transfers', schema=None) as batch_op:
        batch_op.drop_index('ix_blockchain_transfers_transaction_hash')
        batch_op.drop_index('ix_blockchain_transfers_to_wallet')
        batch_op.drop_index('ix_blockchain_transfers_from_wallet')
    op.drop_table('blockchain_transfers')
    with op.batch_alter_table('blockchain_assets', schema=None) as batch_op:
        batch_op.drop_index('ix_blockchain_assets_mint_transaction_hash')
        batch_op.drop_index('ix_blockchain_assets_owner_wallet')
        batch_op.drop_index('ix_blockchain_assets_token_id')
    op.drop_table('blockchain_assets')

    # Rows that hold NULL in these columns must be fixed by hand before downgrading.
    for table, column, type_ in reversed(RELAXED):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(column, existing_type=type_, nullable=False)

    with op.batch_alter_table('collectible_verifications', schema=None) as batch_op:
        batch_op.drop_constraint('fk_collectible_verifications_photos_verified_by_users', type_='foreignkey')
        batch_op.drop_constraint('fk_collectible_verifications_verified_by_users', type_='foreignkey')
        batch_op.alter_column('photos_verified_by', existing_type=sa.Integer(), type_=sa.String(length=100), existing_nullable=True)
        batch_op.alter_column('verified_by', existing_type=sa.Integer(), type_=sa.String(length=100), existing_nullable=True)
        batch_op.create_unique_constraint('certificate_number', ['certificate_number'])

    with op.batch_alter_table('card_images', schema=None) as batch_op:
        batch_op.drop_column('url')

    with op.batch_alter_table('collectible_cards', schema=None) as batch_op:
        batch_op.drop_index('ix_collectible_cards_platform_card_id')
        batch_op.drop_column('platform_card_id')
