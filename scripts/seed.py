"""Load demo data. Safe to re-run: skips if users already exist.

Creates the demo accounts below, the card types, the "Trading Cards" category and 10 demo trading cards
(scripts/seed_collectible_cards.py) for Sarah Seller. The cards are submitted, not verified: sign in as the admin
and verify them through the checklist at /admin/cards/verify, as for any real submission. A card can only be
auctioned once it is verified, so a fresh install has no live auctions.

Run from the project root:  python scripts/seed.py
Demo accounts below are for local development only.
"""
import importlib.util
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402

DEMO_PASSWORD = "Demo@1234"

USERS = [
    ("Admin User", "admin@demo.test", "admin"),
    ("Sarah Seller", "seller1@demo.test", "seller"),
    ("Sam Seller", "seller2@demo.test", "seller"),
    ("Bella Buyer", "buyer1@demo.test", "buyer"),
    ("Ben Buyer", "buyer2@demo.test", "buyer"),
]
CARD_SELLER = "seller1@demo.test"


def _script(name):
    """Load a sibling script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed(app, rng=None):
    """Seed inside an app context. Returns the created demo cards, or None if the database already has users."""
    db.create_all()
    if User.query.first():
        return None
    for name, email, role in USERS:
        u = User(name=name, email=email, role=role, phone="9000000000", address="Demo Street, Demo City")
        u.set_password(DEMO_PASSWORD)
        db.session.add(u)
    db.session.commit()
    _script("seed_card_types").seed()
    _, cards = _script("seed_collectible_cards").seed(app, CARD_SELLER, rng or random.Random(1))
    return cards


def main():
    app = create_app()
    with app.app_context():
        cards = seed(app)
        if cards is None:
            print("Database already seeded, nothing to do.")
            return
        print(f"Seeded {len(USERS)} users and {len(cards)} demo trading cards for {CARD_SELLER} (pending verification).")
        print("Sign in as admin@demo.test and verify them at /admin/cards/verify before they can be auctioned.")
        print(f"Demo password for all accounts: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
