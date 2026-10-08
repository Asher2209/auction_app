"""drop product_details, the generic-marketplace detail fields (Electronics, Fashion, Books, Sports, Home & Garden)

Revision ID: j20dropproddetails
Revises: i19catchup01
Create Date: 2026-10-08 00:00:00.000000

ChainBid lists trading cards only, and a card's details live in collectible_cards. The generic seller form that
wrote product_details never showed its detail fields, so every row holds only product_id and timestamps: nothing
is lost by dropping the table. downgrade() recreates it empty, exactly as e16f1proddetails made it.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'j20dropproddetails'
down_revision = 'i19catchup01'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('product_details')


def downgrade():
    op.create_table('product_details',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('condition', sa.String(length=50), nullable=True),
    sa.Column('warranty', sa.String(length=200), nullable=True),
    sa.Column('shipping_weight', sa.String(length=50), nullable=True),
    sa.Column('shipping_dimensions', sa.String(length=100), nullable=True),
    sa.Column('shipping_info', sa.Text(), nullable=True),
    sa.Column('storage_info', sa.Text(), nullable=True),
    sa.Column('brand', sa.String(length=100), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('color', sa.String(length=50), nullable=True),
    sa.Column('processor', sa.String(length=100), nullable=True),
    sa.Column('ram', sa.String(length=50), nullable=True),
    sa.Column('storage', sa.String(length=50), nullable=True),
    sa.Column('battery', sa.String(length=100), nullable=True),
    sa.Column('screen_size', sa.String(length=50), nullable=True),
    sa.Column('artist_name', sa.String(length=100), nullable=True),
    sa.Column('edition', sa.String(length=100), nullable=True),
    sa.Column('authentication', sa.String(length=200), nullable=True),
    sa.Column('rarity', sa.String(length=100), nullable=True),
    sa.Column('provenance', sa.Text(), nullable=True),
    sa.Column('size', sa.String(length=50), nullable=True),
    sa.Column('fabric', sa.String(length=100), nullable=True),
    sa.Column('fit', sa.String(length=100), nullable=True),
    sa.Column('care_instructions', sa.Text(), nullable=True),
    sa.Column('designer', sa.String(length=100), nullable=True),
    sa.Column('author', sa.String(length=100), nullable=True),
    sa.Column('isbn', sa.String(length=20), nullable=True),
    sa.Column('publication_year', sa.Integer(), nullable=True),
    sa.Column('publisher', sa.String(length=100), nullable=True),
    sa.Column('pages', sa.Integer(), nullable=True),
    sa.Column('language', sa.String(length=50), nullable=True),
    sa.Column('binding', sa.String(length=50), nullable=True),
    sa.Column('sport_type', sa.String(length=100), nullable=True),
    sa.Column('sport_brand', sa.String(length=100), nullable=True),
    sa.Column('size_sport', sa.String(length=50), nullable=True),
    sa.Column('material_sport', sa.String(length=100), nullable=True),
    sa.Column('furniture_type', sa.String(length=100), nullable=True),
    sa.Column('material_home', sa.String(length=100), nullable=True),
    sa.Column('dimensions_home', sa.String(length=100), nullable=True),
    sa.Column('assembly_required', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id')
    )
    op.create_index(op.f('ix_product_details_product_id'), 'product_details', ['product_id'], unique=False)
