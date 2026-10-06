"""Add url column to card_images table for API-hosted images"""
from alembic import op
import sqlalchemy as sa

revision = 'add_url_to_card_images'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('card_images', sa.Column('url', sa.String(500), nullable=True))

def downgrade():
    op.drop_column('card_images', 'url')
