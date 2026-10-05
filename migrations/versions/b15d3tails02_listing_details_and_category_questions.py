"""listing details and category questions

Revision ID: b15d3tails02
Revises: a14c0nsent01
Create Date: 2026-10-04 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b15d3tails02'
down_revision = 'a14c0nsent01'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('condition', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('known_issues', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('whats_included', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('pickup_location', sa.String(length=120), nullable=True))

    op.create_table(
        'category_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('choices', sa.Text(), nullable=True),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('help', sa.String(length=200), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category_id', 'key'),
    )
    with op.batch_alter_table('category_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_category_questions_category_id'), ['category_id'], unique=False)

    op.create_table(
        'product_answers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=True),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('value', sa.String(length=1000), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['question_id'], ['category_questions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('product_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_product_answers_product_id'), ['product_id'], unique=False)


def downgrade():
    with op.batch_alter_table('product_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_product_answers_product_id'))
    op.drop_table('product_answers')
    with op.batch_alter_table('category_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_category_questions_category_id'))
    op.drop_table('category_questions')
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('pickup_location')
        batch_op.drop_column('whats_included')
        batch_op.drop_column('known_issues')
        batch_op.drop_column('condition')
