import io
import os
from datetime import timedelta
from decimal import Decimal

import pytest
from PIL import Image

from app.blueprints.seller.routes_cards import CARD_CATEGORY_NAME
from app.extensions import db
from app.models import Auction, Bid, CardType, Category, Product, ProductImage, utcnow

from .conftest import login, make_user

FMT = "%Y-%m-%dT%H:%M"


def img_bytes(fmt="PNG", size=(20, 20)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, fmt)
    buf.seek(0)
    return buf


def img(name="a.png", fmt="PNG"):
    return (img_bytes(fmt), name)


@pytest.fixture
def cat(app):
    c = Category(name=CARD_CATEGORY_NAME)  # the category the card form files every card under
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def card_type(app, tmp_path):
    """A card type to list under. The card form also writes a QR code file, so static files go to a temp folder."""
    app.static_folder = str(tmp_path / "static")
    t = CardType(name="Pokemon", slug="pokemon")
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def seller(client, users, cat):
    login(client, "seller@t.test")
    return users["seller"]


def form_data(card_type, **over):
    """A valid card form submission (the only way a seller lists anything)."""
    data = {"card_type_id": card_type.id, "card_name": "Charizard", "set_name": "Base Set", "release_year": "1999",
            "card_number": "4/102", "condition": "Near Mint", "language": "English", "confirm_accuracy": "y",
            "card_images": [img()]}
    data.update(over)
    return data


def post_new(client, card_type, **over):
    return client.post("/seller/cards/new", data=form_data(card_type, **over), content_type="multipart/form-data")


def make_product(owner, cat, auction=None, **kw):
    start = utcnow() + timedelta(hours=1)
    kw.setdefault("title", "P")
    p = Product(seller_id=owner.id, category_id=cat.id, description="d" * 12,
                starting_price=Decimal("100"), auction_start=start, auction_end=start + timedelta(days=1),
                approval_status=kw.pop("approval_status", "pending"), **kw)
    p.images.append(ProductImage(path="products/x.png"))
    db.session.add(p)
    db.session.commit()
    if auction:
        a = Auction(product_id=p.id, start_time=auction["start"], end_time=auction["start"] + timedelta(days=1),
                    original_end_time=auction["start"] + timedelta(days=1), current_bid=Decimal("100"),
                    status=auction["status"])
        db.session.add(a)
        db.session.commit()
    return p


# ---- create (through the card form) ---------------------------------------
def test_the_old_product_form_sends_sellers_to_the_card_form(client, seller):
    r = client.get("/seller/products/new")
    assert r.status_code == 302 and r.location.endswith("/seller/cards/new")
    assert client.post("/seller/products/new").status_code == 405


def test_create_product_success(client, seller, cat, card_type, app):
    r = post_new(client, card_type, card_images=[img("one.png"), img("two.jpg", "JPEG")])
    assert r.status_code == 302
    p = Product.query.one()
    assert p.seller_id == seller.id and p.approval_status == "pending" and p.category_id == cat.id
    assert p.collectible_card is not None and len(p.images) == 2
    page = client.get(r.headers["Location"]).data.decode()
    assert f"Platform ID: {p.collectible_card.platform_card_id}." in page and "&lt;strong&gt;" not in page
    for i in p.images:
        assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], i.path))
        assert "one" not in i.path  # user-supplied name is never reused


def test_create_requires_image(client, seller, card_type):
    r = post_new(client, card_type, card_images=[])
    assert r.status_code == 200 and b"at least one image" in r.data
    assert Product.query.count() == 0


def test_create_rejects_too_many_images(client, seller, card_type):
    r = post_new(client, card_type, card_images=[img(f"{i}.png") for i in range(11)])
    assert b"at most 10" in r.data and Product.query.count() == 0


def test_upload_rejects_non_image_with_image_extension(client, seller, card_type, app):
    fake = (io.BytesIO(b"<?php echo 1; ?>"), "shell.png")
    r = post_new(client, card_type, card_images=[fake])
    assert b"not a valid image" in r.data and Product.query.count() == 0
    assert not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "products")) or \
        not os.listdir(os.path.join(app.config["UPLOAD_FOLDER"], "products"))


def test_upload_rejects_bad_extension_and_real_image_renamed(client, seller, card_type):
    for name in ("x.exe", "x.svg", "noext"):
        assert b"Images only" in post_new(client, card_type, card_images=[(img_bytes(), name)]).data, name
    assert Product.query.count() == 0


def test_upload_rejects_unsupported_format_even_if_named_png(client, seller, card_type):
    r = post_new(client, card_type, card_images=[(img_bytes("BMP"), "x.png")])
    assert b"unsupported image type" in r.data and Product.query.count() == 0


def test_upload_rejects_oversized_image(client, seller, card_type, app):
    app.config["MAX_IMAGE_BYTES"] = 10
    r = post_new(client, card_type, card_images=[img()])
    assert b"larger than" in r.data and Product.query.count() == 0


def test_one_bad_file_stores_nothing(client, seller, card_type, app):
    post_new(client, card_type, card_images=[img("ok.png"), (io.BytesIO(b"junk"), "bad.png")])
    folder = os.path.join(app.config["UPLOAD_FOLDER"], "products")
    assert Product.query.count() == 0
    assert not os.path.exists(folder) or not os.listdir(folder)


@pytest.mark.parametrize("over,msg", [
    ({"card_name": "a"}, b"between 2 and 255"),
    ({"card_name": ""}, b"This field is required"),
    ({"card_type_id": 9999}, b"Not a valid choice"),
    ({"condition": "Shiny"}, b"Not a valid choice"),
    ({"confirm_accuracy": ""}, b"You must agree to continue."),
])
def test_create_validation(client, seller, card_type, over, msg):
    r = post_new(client, card_type, **over)
    assert r.status_code == 200 and msg in r.data and Product.query.count() == 0


def test_xss_in_title_is_escaped(client, seller, card_type):
    created = post_new(client, card_type, card_name="<script>alert(1)</script>")
    assert created.status_code == 302
    r = client.get(created.headers["Location"])  # the new card's page shows its name (and the flash repeats it)
    assert b"<script>alert(1)</script>" not in r.data and b"&lt;script&gt;" in r.data


# ---- access control -----------------------------------------------------
def test_only_sellers_can_use_seller_pages(client, users, cat):
    for role in ("buyer", "admin"):
        client.post("/auth/logout")
        login(client, f"{role}@t.test")
        assert client.get("/seller/").status_code == 403
        assert client.get("/seller/products/new").status_code == 403
        assert client.post("/seller/products/1/delete").status_code == 403
    client.post("/auth/logout")
    assert client.get("/seller/products/new").status_code == 302


def test_cannot_touch_another_sellers_product(client, seller, cat):
    other = make_user("other@t.test", "seller")
    p = make_product(other, cat)
    assert client.get(f"/seller/products/{p.id}").status_code == 404
    assert client.get(f"/seller/products/{p.id}/edit").status_code == 404
    assert client.post(f"/seller/products/{p.id}/edit", data={"title": "Hacked"}).status_code == 404
    assert client.post(f"/seller/products/{p.id}/delete").status_code == 404
    assert db.session.get(Product, p.id) is not None


# ---- edit ---------------------------------------------------------------
def test_a_listing_without_a_card_can_no_longer_be_edited(client, seller, cat):
    """Listings from before the cards-only site have no card record; they can be deleted, not edited."""
    p = make_product(seller, cat, approval_status="approved")
    page = f"/seller/products/{p.id}"
    for r in (client.get(f"{page}/edit"), client.post(f"{page}/edit", data={"title": "New Title"})):
        assert r.status_code == 302 and r.location.endswith(page)
    html = client.get(page).data.decode()
    assert "can no longer be edited" in html and f"{page}/edit" not in html and f"{page}/delete" in html
    db.session.expire_all()
    assert db.session.get(Product, p.id).title == "P" and db.session.get(Product, p.id).approval_status == "approved"


def test_cannot_edit_or_delete_after_auction_starts(client, seller, cat):
    for status, start in [("active", utcnow() - timedelta(hours=1)), ("closed", utcnow() - timedelta(days=2)),
                          ("scheduled", utcnow() - timedelta(minutes=1))]:
        p = make_product(seller, cat, approval_status="approved", auction={"start": start, "status": status})
        assert client.get(f"/seller/products/{p.id}/edit").status_code == 302
        r = client.post(f"/seller/products/{p.id}/edit", data={"title": "Hacked"})
        assert r.status_code == 302
        assert client.post(f"/seller/products/{p.id}/delete").status_code == 302
        db.session.expire_all()
        got = db.session.get(Product, p.id)
        assert got is not None and got.title == "P"


def test_cannot_edit_scheduled_auction_with_bids(client, seller, cat, users):
    p = make_product(seller, cat, approval_status="approved",
                     auction={"start": utcnow() + timedelta(hours=1), "status": "scheduled"})
    db.session.add(Bid(auction_id=p.auction.id, buyer_id=users["buyer"].id, amount=Decimal("150")))
    db.session.commit()
    assert not db.session.get(Product, p.id).is_editable


# ---- delete -------------------------------------------------------------
def test_delete_removes_product_auction_and_files(client, seller, cat, app):
    p = make_product(seller, cat, auction={"start": utcnow() + timedelta(hours=1), "status": "scheduled"})
    path = os.path.join(app.config["UPLOAD_FOLDER"], p.images[0].path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(img_bytes().getvalue())
    assert client.post(f"/seller/products/{p.id}/delete").status_code == 302
    assert Product.query.count() == 0 and ProductImage.query.count() == 0 and Auction.query.count() == 0
    assert not os.path.exists(path)


def test_delete_requires_post(client, seller, cat):
    p = make_product(seller, cat)
    assert client.get(f"/seller/products/{p.id}/delete").status_code == 405


# ---- dashboard ----------------------------------------------------------
def test_detail_shows_highest_bid_and_winner(client, seller, cat, users):
    from app.models import Winner
    p = make_product(seller, cat, approval_status="approved",
                     auction={"start": utcnow() - timedelta(days=3), "status": "closed"})
    a = p.auction
    a.current_bid = Decimal("900")
    db.session.add_all([
        Bid(auction_id=a.id, buyer_id=users["buyer"].id, amount=Decimal("900")),
        Winner(auction_id=a.id, buyer_id=users["buyer"].id, winning_amount=Decimal("900")),
    ])
    db.session.commit()
    d = client.get(f"/seller/products/{p.id}").data
    assert b"900.00" in d and b"Winner" in d and b"buyer" in d
