"""scripts/seed_collectible_cards.py: demo cards are made the way the seller form makes them, and stay unverified."""
import importlib.util
import io
import random
from pathlib import Path

import pytest
from PIL import Image

from app.extensions import db
from app.models import CardType, CollectibleCard, CollectibleVerification
from app.blueprints.seller.routes_cards import CARD_CATEGORY_NAME

from .test_payments import client_for

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "seed_collectible_cards.py"
FETCH = ROOT / "scripts" / "fetch_demo_card_images.py"


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


def test_seeding_makes_ten_pending_cards_with_platform_ids_and_images(app, users, card_types, seed_script, tmp_path):
    seller, created = seed_script.seed(app, rng=random.Random(1), image_dir=tmp_path / "no-scans")  # placeholders
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


def png_bytes(fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (30, 42), "gold").save(buf, fmt)
    return buf.getvalue()


def test_the_demo_cards_are_the_real_base_set_holo_rares_and_ungraded(app, users, card_types, seed_script):
    _, created = seed_script.seed(app, rng=random.Random(1), image_dir=None)
    by_name = {c.card_name: c for c in created}
    charizard = by_name["Charizard Base Set"]
    assert charizard.card_number == "4/102" and charizard.release_year == 1999 and charizard.rarity == "Rare Holo"
    assert charizard.manufacturer == "Wizards of the Coast" and charizard.card_type.slug == "pokemon"
    assert charizard.get_type_details()["illustrator"] == "Mitsuhiro Arita" and charizard.get_type_details()["hp"] == 120
    assert "4/102 (1999)" in charizard.product.description
    assert {c.card_number for c in created} == {f"{n}/102" for n in (1, 2, 3, 4, 6, 10, 12, 14, 15, 16)}
    assert all(c.get_type_details()["holo_type"] == "Holo" for c in created)  # a value the seller form offers
    # no made-up grading certificate can collide with a real one
    assert all(not c.is_graded and c.certification_number is None and c.grading_company is None for c in created)


def test_a_downloaded_scan_becomes_the_front_image(app, users, card_types, seed_script, tmp_path):
    scans = tmp_path / "scans"
    scans.mkdir()
    (scans / "base1-4.png").write_bytes(png_bytes())
    _, created = seed_script.seed(app, rng=random.Random(1), image_dir=scans)
    upload = Path(app.config["UPLOAD_FOLDER"])
    by_name = {c.card_name: c for c in created}
    front = by_name["Charizard Base Set"].images[0].path
    assert (upload / front).read_bytes() == png_bytes() and "base1" not in front  # copied under a random name
    assert (upload / by_name["Mewtwo Base Set"].images[0].path).read_bytes() != png_bytes()  # no scan: placeholder


@pytest.fixture
def fetch_script():
    spec = importlib.util.spec_from_file_location("fetch_demo_card_images", FETCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeReply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetching_saves_a_png_scan_from_the_official_image_host(fetch_script, tmp_path):
    asked = []

    def opener(request, timeout):
        asked.append(request.full_url)
        return FakeReply(png_bytes())

    card = {"api_id": "base1-4", "name": "Charizard"}
    path = fetch_script.fetch(card, tmp_path, opener=opener)
    assert asked == ["https://images.pokemontcg.io/base1/4_hires.png"]
    assert path == tmp_path / "base1-4.png" and path.read_bytes() == png_bytes()


@pytest.mark.parametrize("body", [b"<html>not found</html>", png_bytes("JPEG"), b"\x89PNG\r\n\x1a\n" + b"x" * 6_000_000],
                         ids=["html-page", "jpeg", "too-big"])
def test_fetching_refuses_anything_but_a_png_of_sensible_size(fetch_script, tmp_path, body):
    with pytest.raises(ValueError):
        fetch_script.fetch({"api_id": "base1-4"}, tmp_path, opener=lambda request, timeout: FakeReply(body))
    assert not (tmp_path / "base1-4.png").exists()


def test_the_scans_are_never_committed():
    """The official artwork belongs to The Pokemon Company and this repository is public."""
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "scripts/demo_card_images/" in ignored
