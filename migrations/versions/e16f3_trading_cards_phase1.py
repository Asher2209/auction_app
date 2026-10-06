"""Add trading cards marketplace Phase 1 models

Revision ID: e16f3tradingcards
Revises: e16f2collectibles
Create Date: 2026-10-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e16f3tradingcards'
down_revision = 'e16f2collectibles'
branch_labels = None
depends_on = None


def upgrade():
    # Create card_types table
    op.create_table(
        'card_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('field_schema', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug')
    )

    # Create collectible_cards table
    op.create_table(
        'collectible_cards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('card_type_id', sa.Integer(), nullable=False),
        sa.Column('card_name', sa.String(length=255), nullable=False),
        sa.Column('manufacturer', sa.String(length=100), nullable=True),
        sa.Column('set_name', sa.String(length=100), nullable=True),
        sa.Column('set_code', sa.String(length=50), nullable=True),
        sa.Column('release_year', sa.Integer(), nullable=True),
        sa.Column('card_number', sa.String(length=50), nullable=True),
        sa.Column('rarity', sa.String(length=50), nullable=True),
        sa.Column('condition', sa.String(length=50), nullable=False),
        sa.Column('condition_notes', sa.Text(), nullable=True),
        sa.Column('language', sa.String(length=50), nullable=False, server_default='English'),
        sa.Column('country', sa.String(length=50), nullable=True),
        sa.Column('edition', sa.String(length=100), nullable=True),
        sa.Column('is_graded', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('grading_company', sa.String(length=100), nullable=True),
        sa.Column('grade', sa.String(length=20), nullable=True),
        sa.Column('certification_number', sa.String(length=100), nullable=True),
        sa.Column('certification_url', sa.String(length=500), nullable=True),
        sa.Column('estimated_value', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('type_details', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['card_type_id'], ['card_types.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id')
    )

    # Create card_images table
    op.create_table(
        'card_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collectible_card_id', sa.Integer(), nullable=False),
        sa.Column('image_type', sa.String(length=50), nullable=False),
        sa.Column('path', sa.String(length=255), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['collectible_card_id'], ['collectible_cards.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create card_verification_checklists table
    op.create_table(
        'card_verification_checklists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('verification_id', sa.Integer(), nullable=False),
        sa.Column('check_type', sa.String(length=100), nullable=False),
        sa.Column('result', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['verification_id'], ['collectible_verifications.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create card_verification_history table
    op.create_table(
        'card_verification_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('verification_id', sa.Integer(), nullable=False),
        sa.Column('previous_status', sa.String(length=50), nullable=True),
        sa.Column('new_status', sa.String(length=50), nullable=False),
        sa.Column('changed_by', sa.Integer(), nullable=True),
        sa.Column('change_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['verification_id'], ['collectible_verifications.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Extend collectible_verifications table with new columns (simple approach without batch operations)
    op.add_column('collectible_verifications', sa.Column('collectible_card_id', sa.Integer(), nullable=True))
    op.add_column('collectible_verifications', sa.Column('is_graded', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('collectible_verifications', sa.Column('admin_notes', sa.Text(), nullable=True))
    op.add_column('collectible_verifications', sa.Column('rejection_reason', sa.String(length=255), nullable=True))
    op.add_column('collectible_verifications', sa.Column('seller_response', sa.Text(), nullable=True))
    op.add_column('collectible_verifications', sa.Column('submission_count', sa.Integer(), nullable=False, server_default='1'))

    # Add foreign key for collectible_card_id
    op.create_foreign_key('fk_collectible_verifications_collectible_card_id', 'collectible_verifications',
                          'collectible_cards', ['collectible_card_id'], ['id'])


def downgrade():
    # Drop foreign key
    op.drop_constraint('fk_collectible_verifications_collectible_card_id', 'collectible_verifications', type_='foreignkey')

    # Drop columns from collectible_verifications
    op.drop_column('collectible_verifications', 'submission_count')
    op.drop_column('collectible_verifications', 'seller_response')
    op.drop_column('collectible_verifications', 'rejection_reason')
    op.drop_column('collectible_verifications', 'admin_notes')
    op.drop_column('collectible_verifications', 'is_graded')
    op.drop_column('collectible_verifications', 'collectible_card_id')

    # Drop new tables
    op.drop_table('card_verification_history')
    op.drop_table('card_verification_checklists')
    op.drop_table('card_images')
    op.drop_table('collectible_cards')
    op.drop_table('card_types')
