"""scripts/seed_collectible_cards.py: demo cards are made the way the seller form makes them, and stay unverified."""
import importlib.util
import random
from pathlib import Path

import pytest

from app.extensions import db
from app.models import CardType, CollectibleCard, CollectibleVerification
from app.blueprints.seller.routes_cards import CARD_CATEGORY_NAME

from .test_payments import client_for

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_collectible_cards.py"


@pytest.fixture
def seed_script():
    spec = importlib.util.spec_from_file_location("seed_collectible_cards", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # importing it must not build an app or touch a database
    return module


@pytest.fixture
def card_types(app):
    db.session.add_all([CardType(name="Pokemon", slug="pokemon"), CardType(name="Football", slug="football")])
    db.session.commit()


def test_seeding_makes_ten_pending_cards_with_platform_ids_and_images(app, users, card_types, seed_script):
    seller, created = seed_script.seed(app, rng=random.Random(1))
    assert seller.email == "seller@t.test" and len(created) == 10
    for card in created:
        assert card.platform_card_id == f"CARD-{card.id:06d}"
        assert card.product.category.name == CARD_CATEGORY_NAME and card.product.approval_status == "pending"
        assert card.images and (Path(app.config["UPLOAD_FOLDER"]) / card.images[0].path).is_file()
        assert card.get_type_details()
    statuses = {v.verification_status for v in CollectibleVerification.query}
    assert statuses == {"pending"}  # nothing skips the admin checklist


def test_seeding_twice_adds_nothing(app, users, card_types, seed_script):
    seed_script.seed(app, rng=random.Random(1))
    _, again = seed_script.seed(app, rng=random.Random(2))
    assert again == [] and CollectibleCard.query.count() == 10


def test_seeding_explains_what_is_missing(app, users, seed_script):
    with pytest.raises(SystemExit, match="seed_card_types"):
        seed_script.seed(app)
    with pytest.raises(SystemExit, match="No seller"):
        seed_script.seed(app, seller_email="nobody@t.test")


def test_seeded_cards_show_on_the_seller_and_admin_pages(app, users, card_types, seed_script):
    seed_script.seed(app, rng=random.Random(1))
    seller_page = client_for(app, "seller@t.test").get("/seller/collectibles")
    assert seller_page.status_code == 200 and "Charizard Base Set" in seller_page.get_data(as_text=True)
    admin = client_for(app, "admin@t.test")
    queue = admin.get("/admin/cards/verify")
    assert queue.status_code == 200 and "Mewtwo Base Set" in queue.get_data(as_text=True)
    first = CollectibleVerification.query.first()
    assert admin.get(f"/admin/cards/verify/{first.id}").status_code == 200
