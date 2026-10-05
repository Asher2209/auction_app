"""Add collectible verification tables

Revision ID: e16f2collectibles
Revises: e16f1proddetails
Create Date: 2026-10-05 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e16f2collectibles'
down_revision = 'e16f1proddetails'
branch_labels = None
depends_on = None


def upgrade():
    # Create supported_graders table
    op.create_table(
        'supported_graders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('api_endpoint', sa.String(length=500), nullable=True),
        sa.Column('api_key_required', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('api_key_name', sa.String(length=50), nullable=True),
        sa.Column('cert_types', sa.String(length=500), nullable=True),
        sa.Column('lookup_method', sa.String(length=50), nullable=True),
        sa.Column('lookup_instructions', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('last_tested', sa.DateTime(), nullable=True),
        sa.Column('is_working', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Create collectible_verifications table
    op.create_table(
        'collectible_verifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('collectible_type', sa.String(length=100), nullable=False),
        sa.Column('grader', sa.String(length=100), nullable=False),
        sa.Column('certificate_number', sa.String(length=100), nullable=False),
        sa.Column('grade', sa.String(length=20), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('verification_status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('verification_date', sa.DateTime(), nullable=True),
        sa.Column('verified_by', sa.String(length=100), nullable=True),
        sa.Column('grader_item_name', sa.String(length=255), nullable=True),
        sa.Column('grader_cert_url', sa.String(length=500), nullable=True),
        sa.Column('grader_response', sa.Text(), nullable=True),
        sa.Column('slab_photo_urls', sa.Text(), nullable=True),
        sa.Column('photos_verified', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('photos_verified_by', sa.String(length=100), nullable=True),
        sa.Column('photos_verified_date', sa.DateTime(), nullable=True),
        sa.Column('duplicate_flag', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('previous_listing_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id'),
        sa.UniqueConstraint('certificate_number'),
        sa.Index('ix_certificate_number', 'certificate_number')
    )

    # Create verification_logs table
    op.create_table(
        'verification_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collectible_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('performed_by', sa.String(length=100), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['collectible_id'], ['collectible_verifications.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('verification_logs')
    op.drop_table('collectible_verifications')
    op.drop_table('supported_graders')
