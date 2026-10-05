"""user consent record

Revision ID: a14c0nsent01
Revises: f9313f44161a
Create Date: 2026-10-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a14c0nsent01'
down_revision = 'f9313f44161a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('consent_version', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('consented_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('consented_at')
        batch_op.drop_column('consent_version')
