from ..extensions import db
from . import utcnow


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    starting_price = db.Column(db.Numeric(12, 2), nullable=False)
    # Requested auction window (UTC). The Auction row is created from these on admin approval.
    auction_start = db.Column(db.DateTime, nullable=False)
    auction_end = db.Column(db.DateTime, nullable=False)
    # pending / approved / rejected
    approval_status = db.Column(db.String(10), nullable=False, default="pending")
    rejection_reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    seller = db.relationship("User", backref="products")
    category = db.relationship("Category", backref="products")
    images = db.relationship("ProductImage", backref="product", cascade="all, delete-orphan")

    @property
    def cover(self):
        return self.images[0].path if self.images else None

    @property
    def is_editable(self):
        """Seller may edit/delete only before the auction starts and while it has no bids."""
        a = self.auction
        if a is None:
            return True
        return a.status == "scheduled" and a.start_time > utcnow() and not a.bids

    @property
    def display_status(self):
        """pending / rejected, or the auction state (scheduled / active / closed / cancelled)."""
        return self.auction.status if self.auction else self.approval_status


class ProductImage(db.Model):
    __tablename__ = "product_images"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    path = db.Column(db.String(255), nullable=False)


class Watchlist(db.Model):
    __tablename__ = "watchlist"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), primary_key=True)
