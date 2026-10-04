"""Load demo data. Safe to re-run: skips if users already exist.

Run from the project root:  python scripts/seed.py
Demo accounts below are for local development only.
"""
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Auction, Category, Product, User, utcnow  # noqa: E402

DEMO_PASSWORD = "Demo@1234"

CATEGORIES = ["Electronics", "Fashion", "Home & Garden", "Collectibles", "Books", "Sports"]

USERS = [
    ("Admin User", "admin@demo.test", "admin"),
    ("Sarah Seller", "seller1@demo.test", "seller"),
    ("Sam Seller", "seller2@demo.test", "seller"),
    ("Bella Buyer", "buyer1@demo.test", "buyer"),
    ("Ben Buyer", "buyer2@demo.test", "buyer"),
]

# (title, category, description, starting price, hours until end, seller email)
PRODUCTS = [
    ("Gaming Laptop 16GB", "Electronics", "Lightly used, 1 year warranty left.", 40000, 48, "seller1@demo.test"),
    ("Mechanical Keyboard", "Electronics", "Hot-swappable, brown switches.", 2500, 24, "seller1@demo.test"),
    ("Vintage Film Camera", "Collectibles", "Working 35mm camera from the 1980s.", 6000, 72, "seller2@demo.test"),
    ("Leather Jacket", "Fashion", "Genuine leather, size M.", 3500, 30, "seller2@demo.test"),
    ("Cricket Bat (Willow)", "Sports", "English willow, grade 1.", 4500, 12, "seller2@demo.test"),
    ("First-Edition Novel", "Books", "Signed first edition, good condition.", 8000, 96, "seller1@demo.test"),
]


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        if User.query.first():
            print("Database already seeded, nothing to do.")
            return

        cats = {n: Category(name=n) for n in CATEGORIES}
        db.session.add_all(cats.values())

        users = {}
        for name, email, role in USERS:
            u = User(name=name, email=email, role=role, phone="9000000000", address="Demo Street, Demo City")
            u.set_password(DEMO_PASSWORD)
            users[email] = u
            db.session.add(u)
        db.session.flush()

        now = utcnow()
        for title, cat, desc, price, hours, seller in PRODUCTS:
            end = now + timedelta(hours=hours)
            p = Product(
                seller_id=users[seller].id, category_id=cats[cat].id, title=title,
                description=desc, starting_price=Decimal(price), approval_status="approved",
                auction_start=now, auction_end=end,
            )
            db.session.add(p)
            db.session.flush()
            db.session.add(Auction(
                product_id=p.id, start_time=now, end_time=end, original_end_time=end,
                current_bid=Decimal(price), status="active",
            ))
        db.session.commit()
        print(f"Seeded {len(USERS)} users, {len(CATEGORIES)} categories, {len(PRODUCTS)} auctions.")
        print(f"Demo password for all accounts: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
