"""scripts/seed.py and scripts/seed_demo_activity.py: a fresh install shows only trading-card content, nothing verified."""
import importlib.util
import random
from pathlib import Path

import pytest

from app.blueprints.seller.routes_cards import CARD_CATEGORY_NAME
from app.models import Auction, Category, CollectibleCard, CollectibleVerification, Product, User

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FORBIDDEN = ("authentic", "verified seller", "certified")


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # importing it must not build an app or touch a database
    return module


@pytest.fixture
def seed_script():
    return load("seed")


def test_seed_makes_the_demo_accounts_and_pending_trading_cards_only(app, seed_script):
    cards = seed_script.seed(app, rng=random.Random(1))
    for name, email, role in seed_script.USERS:
        user = User.query.filter_by(email=email).one()
        assert (user.name, user.role) == (name, role) and user.check_password("Demo@1234")
    assert [c.name for c in Category.query] == [CARD_CATEGORY_NAME]
    assert len(cards) == 10 and CollectibleCard.query.count() == 10
    assert {c.product.seller.email for c in cards} == {"seller1@demo.test"}
    assert {v.verification_status for v in CollectibleVerification.query} == {"pending"}
    assert {p.approval_status for p in Product.query} == {"pending"}
    assert Auction.query.count() == 0  # a card is auctioned only after an admin verifies it


def test_seed_twice_adds_nothing(app, seed_script):
    seed_script.seed(app, rng=random.Random(1))
    assert seed_script.seed(app, rng=random.Random(2)) is None
    assert User.query.count() == 5 and CollectibleCard.query.count() == 10


def test_demo_activity_builds_card_history_on_top_of_seed(app, seed_script):
    seed_script.seed(app, rng=random.Random(1))
    made = load("seed_demo_activity").seed(random.Random(7))
    assert made["closed"] > 0 and made["paid"] > 0
    assert [c.name for c in Category.query] == [CARD_CATEGORY_NAME]
    assert {s for (s,) in Auction.query.with_entities(Auction.status).distinct()} == {"closed", "active", "scheduled", "cancelled"}
    assert {v.verification_status for v in CollectibleVerification.query} == {"pending"}  # history adds no verified cards
    for p in Product.query:
        text = f"{p.title} {p.description}".lower()
        assert not any(word in text for word in FORBIDDEN), p.title


def test_demo_activity_needs_seed_first(app):
    with pytest.raises(SystemExit, match="seed.py"):
        load("seed_demo_activity").seed()
