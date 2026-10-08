"""Phase 1: Platform Card ID, QR code, seller card page, public verification page, backfill."""
import importlib.util
import io
import re
from pathlib import Path

import pytest
import zxingcpp
from PIL import Image

from app.extensions import db
from app.models import CardType, CollectibleCard, CollectibleVerification, Product, ProductImage
from app.services import qrcode_service
from app.services.card_identity_service import assign_platform_card_id

from .conftest import login, make_user
from .test_seller import img
from datetime import timedelta
from decimal import Decimal
from app.models import utcnow

ID_RE = re.compile(r"^CARD-\d{6}$")
DOCUMENTED_PATH = "/collectibles/card-verification/{}"


def public_path(card):
    """The URL the app really serves the public card page on."""
    from flask import current_app
    return current_app.url_map.bind("localhost").build("collectibles.verify_card", {"platform_card_id": card.platform_card_id})


def get_public(client, card):
    r = client.get(public_path(card))
    assert r.status_code == 200, f"public page returned {r.status_code}"
    return r.get_data(as_text=True)


@pytest.fixture
def static_dir(app, tmp_path):
    """Send generated QR files to a temp folder instead of the real static directory."""
    app.static_folder = str(tmp_path / "static")
    return Path(app.static_folder)


@pytest.fixture
def card_type(app):
    t = CardType(name="Pokemon", slug="pokemon")
    db.session.add(t)
    db.session.commit()
    return t


def card_form(card_type, **over):
    data = {"card_type_id": card_type.id, "card_name": "Charizard", "set_name": "Base Set", "release_year": "1999",
            "card_number": "4/102", "condition": "Near Mint", "language": "English", "confirm_accuracy": "y",
            "card_images": [img("front.png"), img("back.png")]}
    data.update(over)
    return data


def create_card_via_form(client, card_type, **over):
    return client.post("/seller/cards/new", data=card_form(card_type, **over), content_type="multipart/form-data")


def db_card(owner, card_type, name="Charizard", status="pending", with_id=True):
    """A card created directly, so public-page tests do not depend on the seller form."""
    from app.models import Category
    cat = Category.query.first() or Category(name="Cards")
    db.session.add(cat)
    db.session.commit()
    start = utcnow() + timedelta(hours=1)
    p = Product(seller_id=owner.id, category_id=cat.id, title=name, description="d" * 12,
                starting_price=Decimal("100"), auction_start=start, auction_end=start + timedelta(days=1))
    p.images.append(ProductImage(path="products/x.png"))
    db.session.add(p)
    db.session.commit()
    c = CollectibleCard(product_id=p.id, card_type_id=card_type.id, card_name=name, condition="Near Mint",
                        set_name="Base Set", card_number="4/102")
    db.session.add(c)
    db.session.commit()
    db.session.add(CollectibleVerification(product_id=p.id, collectible_card_id=c.id, collectible_type="trading_card",
                                           verification_status=status))
    db.session.commit()
    if with_id:
        assign_platform_card_id(c)
    return c


# ---- Create New Card ---------------------------------------------------------
def test_seller_form_creates_card_with_platform_id_and_qr(client, users, card_type, static_dir):
    login(client, "seller@t.test")
    r = create_card_via_form(client, card_type)
    assert r.status_code == 302, r.get_data(as_text=True)[:1500]
    card = CollectibleCard.query.one()
    assert ID_RE.match(card.platform_card_id)
    assert (static_dir / "qrcodes" / f"card_{card.id}_{card.platform_card_id}.png").is_file()
    assert card.product.collectible_verification.verification_status == "pending"


def test_flash_message_after_creation_contains_the_platform_id(client, users, card_type, static_dir):
    login(client, "seller@t.test")
    create_card_via_form(client, card_type)
    with client.session_transaction() as s:
        flashes = [m for _, m in s.get("_flashes", [])]
    card = CollectibleCard.query.one()
    assert any(card.platform_card_id in m for m in flashes), flashes


def test_form_without_image_creates_nothing(client, users, card_type, static_dir):
    login(client, "seller@t.test")
    create_card_via_form(client, card_type, card_images=[])
    assert CollectibleCard.query.count() == 0


def test_buyer_cannot_create_a_card(client, users, card_type, static_dir):
    login(client, "buyer@t.test")
    assert create_card_via_form(client, card_type).status_code == 403
    assert CollectibleCard.query.count() == 0


# ---- Platform Card ID --------------------------------------------------------
def test_platform_ids_are_unique_and_well_formed(users, card_type):
    cards = [db_card(users["seller"], card_type, f"Card {i}") for i in range(5)]
    ids = [c.platform_card_id for c in cards]
    assert all(ID_RE.match(i) for i in ids) and len(set(ids)) == 5


def test_assigning_an_id_twice_keeps_the_first(users, card_type):
    c = db_card(users["seller"], card_type)
    first = c.platform_card_id
    assert assign_platform_card_id(c) == first == c.platform_card_id


def test_database_rejects_a_duplicate_platform_id(users, card_type):
    a = db_card(users["seller"], card_type, "A")
    b = db_card(users["seller"], card_type, "B")
    b.platform_card_id = a.platform_card_id
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


# ---- QR code ------------------------------------------------------------------
def decode_qr(path):
    results = zxingcpp.read_barcodes(Image.open(path))
    assert results, "the saved file contains no readable QR code"
    return results[0].text


def test_qr_png_is_readable_and_names_the_card(app, users, card_type, static_dir):
    c = db_card(users["seller"], card_type)
    rel = qrcode_service.save_qr_code_to_file(c.platform_card_id, c.id)
    assert c.platform_card_id in decode_qr(static_dir / rel)


def test_qr_encodes_an_absolute_url_a_phone_can_open(app, users, card_type, static_dir):
    c = db_card(users["seller"], card_type)
    rel = qrcode_service.save_qr_code_to_file(c.platform_card_id, c.id)
    text = decode_qr(static_dir / rel)
    assert re.match(r"^https?://", text), f"QR holds {text!r}, which a phone scanner cannot open"


def test_qr_leads_to_the_public_page(app, client, users, card_type, static_dir):
    from urllib.parse import urlparse
    c = db_card(users["seller"], card_type, status="verified")
    text = decode_qr(static_dir / qrcode_service.save_qr_code_to_file(c.platform_card_id, c.id))
    assert client.get(urlparse(text).path).status_code == 200, f"scanning the QR ({text}) leads to an error page"


def test_qr_contains_no_personal_data(app, users, card_type, static_dir):
    c = db_card(users["seller"], card_type)
    text = decode_qr(static_dir / qrcode_service.save_qr_code_to_file(c.platform_card_id, c.id))
    assert "seller@t.test" not in text and "@" not in text


def test_inline_svg_qr_is_valid_svg(app, users, card_type):
    c = db_card(users["seller"], card_type)
    svg = qrcode_service.generate_qr_code_svg(c.platform_card_id)
    assert svg.startswith("<svg") and svg.endswith("</svg>") and "<rect" in svg


# ---- View card (seller page) -----------------------------------------------------
def test_seller_card_page_shows_id_qr_and_public_link(client, users, card_type, static_dir):
    c = db_card(users["seller"], card_type)
    qrcode_service.save_qr_code_to_file(c.platform_card_id, c.id)
    login(client, "seller@t.test")
    r = client.get(f"/seller/cards/{c.id}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and c.platform_card_id in html
    assert public_path(c) in html
    src = re.search(r'<img src="([^"]*qrcodes/[^"]+)"', html)
    assert src, "no QR image on the seller card page"
    assert (static_dir / src.group(1).split("/static/")[1]).is_file(), "the QR image the page points to does not exist"


def test_another_seller_cannot_open_the_card_page(client, users, card_type):
    c = db_card(users["seller"], card_type)
    make_user("other@t.test", "seller")
    login(client, "other@t.test")
    assert client.get(f"/seller/cards/{c.id}").status_code == 403


# ---- Public verification page -----------------------------------------------------
def test_public_page_loads_without_login(client, users, card_type):
    c = db_card(users["seller"], card_type, status="verified")
    html = get_public(client, c)
    for text in (c.platform_card_id, "Charizard", "Base Set", "4/102", "Near Mint"):
        assert text in html, text


def test_documented_public_url_resolves(client, users, card_type):
    c = db_card(users["seller"], card_type, status="verified")
    assert client.get(DOCUMENTED_PATH.format(c.platform_card_id)).status_code == 200


def test_public_page_unknown_id_is_404(client):
    assert client.get("/collectibles/card-verification/CARD-999999").status_code == 404


def test_public_page_hides_seller_personal_data(client, users, card_type):
    users["seller"].name = "Rajesh Kumar"
    users["seller"].wallet_address = "0x" + "a1" * 20
    db.session.commit()
    c = db_card(users["seller"], card_type, status="verified")
    html = get_public(client, c)
    for private in ("seller@t.test", "9000000000", "Somewhere", "Rajesh Kumar"):
        assert private not in html, private


def test_public_page_shows_card_images(client, users, card_type):
    from app.models import CardImage
    c = db_card(users["seller"], card_type, status="verified")
    db.session.add(CardImage(collectible_card_id=c.id, image_type="front", path="products/front-photo.png"))
    db.session.commit()
    html = get_public(client, c)
    assert "front-photo.png" in html


@pytest.mark.parametrize("status", ["pending", "under_review", "rejected", "more_info_needed"])
def test_public_page_never_calls_an_unverified_card_platform_verified(client, users, card_type, status):
    c = db_card(users["seller"], card_type, status=status)
    html = get_public(client, c)
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    assert "Platform Verified" not in title, f"{status} card has a title of {title.strip()!r}"
    assert "Platform Verified</span>" not in html, f"{status} card shows the green Platform Verified badge"


def test_public_page_labels_a_verified_card(client, users, card_type):
    c = db_card(users["seller"], card_type, status="verified")
    assert "Platform Verified" in get_public(client, c)


def test_public_page_does_not_overclaim_authenticity(client, users, card_type):
    c = db_card(users["seller"], card_type, status="verified")
    html = get_public(client, c).lower()
    assert "100% authentic" not in html and "guaranteed authentic" not in html


# ---- Backfill script -----------------------------------------------------------------
def load_backfill():
    path = Path(__file__).resolve().parent.parent / "scripts" / "backfill_platform_card_ids.py"
    spec = importlib.util.spec_from_file_location("backfill_platform_card_ids", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_assigns_ids_and_qr_codes_to_existing_cards(app, users, card_type, static_dir):
    cards = [db_card(users["seller"], card_type, f"Old {i}", with_id=False) for i in range(3)]
    assert all(c.platform_card_id is None for c in cards)
    load_backfill().backfill_platform_card_ids()
    for c in cards:
        db.session.refresh(c)
        assert ID_RE.match(c.platform_card_id)
        assert (static_dir / "qrcodes" / f"card_{c.id}_{c.platform_card_id}.png").is_file()


def test_backfill_leaves_existing_ids_alone_and_is_repeatable(app, users, card_type, static_dir):
    keep = db_card(users["seller"], card_type, "Keep")
    before = keep.platform_card_id
    db_card(users["seller"], card_type, "Old", with_id=False)
    backfill = load_backfill()
    backfill.backfill_platform_card_ids()
    backfill.backfill_platform_card_ids()
    db.session.refresh(keep)
    assert keep.platform_card_id == before
    assert CollectibleCard.query.filter_by(platform_card_id=None).count() == 0


# ---- unverified cards must not read as verified anywhere on the page --------------------
@pytest.mark.parametrize("status", ["pending", "under_review", "rejected", "more_info_needed"])
def test_unverified_page_makes_no_verification_claims(client, users, card_type, status):
    c = db_card(users["seller"], card_type, status=status)
    html = get_public(client, c)
    assert "has been reviewed and verified" not in html
    assert "Verified On" not in html
    assert "not been platform verified" in html


def test_verified_page_shows_the_verification_date(client, users, card_type):
    c = db_card(users["seller"], card_type, status="verified")
    c.product.collectible_verification.verification_date = utcnow()
    db.session.commit()
    html = get_public(client, c)
    assert "Verified On" in html and "has been reviewed and verified" in html
    assert "not been platform verified" not in html


def test_backfill_can_regenerate_existing_qr_codes(app, users, card_type, static_dir):
    c = db_card(users["seller"], card_type)
    stale = static_dir / "qrcodes" / f"card_{c.id}_{c.platform_card_id}.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old-and-broken")
    load_backfill().backfill_platform_card_ids(regenerate_qr=True)
    assert c.platform_card_id in decode_qr(stale)
