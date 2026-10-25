"""sign in with Google: users.google_sub

Revision ID: n24google01
Revises: m23sessions01
Create Date: 2026-10-25 00:00:00.000000

Empty for every existing account: an account is linked the first time its owner signs in with Google.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'n24google01'
down_revision = 'm23sessions01'
branch_labels = None
depends_on = None


def upgrade():
    # A unique index rather than a unique constraint: SQLite can add an index in place, while a constraint makes it
    # rebuild the users table, which every other table points at.
    op.add_column('users', sa.Column('google_sub', sa.String(length=255), nullable=True))
    op.create_index('ix_users_google_sub', 'users', ['google_sub'], unique=True)


def downgrade():
    op.drop_index('ix_users_google_sub', table_name='users')
    op.drop_column('users', 'google_sub')  # in place (SQLite 3.35+); a batch rebuild of users would break its foreign keys
