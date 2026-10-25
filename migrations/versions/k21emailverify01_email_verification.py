"""email verification: users.email_verified_at

Revision ID: k21emailverify01
Revises: j20dropproddetails
Create Date: 2026-10-25 00:00:00.000000

Accounts that exist before this migration are counted as verified from the day they were created, so nobody who
already signed up is locked out of bidding or selling. New accounts start unverified until they click the emailed link.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'k21emailverify01'
down_revision = 'j20dropproddetails'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET email_verified_at = created_at")


def downgrade():
    op.drop_column('users', 'email_verified_at')  # in place (SQLite 3.35+); a batch rebuild of users would break its foreign keys
