"""one account buys and sells: users.role 'buyer' and 'seller' become 'member'

Revision ID: o25onerole01
Revises: n24google01
Create Date: 2026-10-25 00:00:00.000000

Admins are unchanged. Going back cannot know which role a member started with, so anyone who has listed a product
becomes a seller and everyone else a buyer.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'o25onerole01'
down_revision = 'n24google01'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE users SET role = 'member' WHERE role IN ('buyer', 'seller')")


def downgrade():
    op.execute("UPDATE users SET role = 'seller' WHERE role = 'member' AND id IN (SELECT seller_id FROM products)")
    op.execute("UPDATE users SET role = 'buyer' WHERE role = 'member'")
