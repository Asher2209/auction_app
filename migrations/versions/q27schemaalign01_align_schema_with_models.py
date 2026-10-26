"""align the schema the migrations build with the models

Revision ID: q27schemaalign01
Revises: p26leases01
Create Date: 2026-10-25 00:00:00.000000

A database built by running every migration (any fresh PostgreSQL) still held what an abandoned feature had added:
the category_questions and product_answers tables and four products columns (condition, known_issues, whats_included,
pickup_location), none of which the code reads. It also lacked indexes the models expect, under the names they expect.
A database made from the models (db.create_all, as older development setups were) already matches, so every step looks
first and changes only what is actually different. `flask db check` in CI keeps the two from drifting apart again.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'q27schemaalign01'
down_revision = 'p26leases01'
branch_labels = None
depends_on = None

OLD_PRODUCT_COLUMNS = ('condition', 'known_issues', 'whats_included', 'pickup_location')
MESSAGE_INDEXES = {'ix_messages_sender_id': 'sender_id', 'ix_messages_recipient_id': 'recipient_id',
                   'ix_messages_product_id': 'product_id'}


def _state():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    indexes = {t: {i['name'] for i in inspector.get_indexes(t)} for t in ('messages', 'collectible_verifications') if t in tables}
    columns = {c['name'] for c in inspector.get_columns('products')}
    return tables, indexes, columns


def upgrade():
    tables, indexes, columns = _state()
    if 'product_answers' in tables:  # refers to category_questions, so it goes first
        op.drop_table('product_answers')
    if 'category_questions' in tables:
        op.drop_table('category_questions')
    for column in OLD_PRODUCT_COLUMNS:
        if column in columns:
            op.drop_column('products', column)  # in place: a batch rebuild of products would trip its foreign keys on SQLite
    verification = indexes.get('collectible_verifications', set())
    if 'ix_certificate_number' in verification:
        op.drop_index('ix_certificate_number', table_name='collectible_verifications')
    if 'ix_collectible_verifications_certificate_number' not in verification:
        op.create_index('ix_collectible_verifications_certificate_number', 'collectible_verifications', ['certificate_number'])
    for name, column in MESSAGE_INDEXES.items():
        if name not in indexes.get('messages', set()):
            op.create_index(name, 'messages', [column])
    _exact_wei_on_sqlite()


def _exact_wei_on_sqlite():
    """SQLite turns a large number in a NUMERIC column into a float, so a wei amount would drift by a few wei. The model
    keeps these two as text on SQLite (payment.ExactDecimal); a database built by the migrations had them as NUMERIC.
    Other databases have an exact NUMERIC and are left alone. Nothing refers to crypto_payments, so rebuilding it is safe."""
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        return
    types = {c['name']: str(c['type']).upper() for c in sa.inspect(bind).get_columns('crypto_payments')}
    if not any(types.get(c, '').startswith('NUMERIC') for c in ('expected_wei', 'amount')):
        return
    with op.batch_alter_table('crypto_payments', schema=None) as batch_op:
        batch_op.alter_column('expected_wei', type_=sa.String(length=64), existing_nullable=True)
        batch_op.alter_column('amount', type_=sa.String(length=64), existing_nullable=False)


def downgrade():
    # The indexes stay: they only speed things up. The abandoned tables and columns come back empty, as before.
    tables, _, columns = _state()
    for column, type_ in (('condition', sa.String(length=12)), ('known_issues', sa.Text()),
                          ('whats_included', sa.String(length=500)), ('pickup_location', sa.String(length=120))):
        if column not in columns:
            op.add_column('products', sa.Column(column, type_, nullable=True))
    if 'category_questions' not in tables:
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
        op.create_index('ix_category_questions_category_id', 'category_questions', ['category_id'])
    if 'product_answers' not in tables:
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
        op.create_index('ix_product_answers_product_id', 'product_answers', ['product_id'])
