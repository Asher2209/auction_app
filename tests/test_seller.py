import io
import os
from datetime import timedelta
from decimal import Decimal

import pytest
from PIL import Image

from app.extensions import db
from app.models import Auction, Bid, Category, Product, ProductImage, User, utcnow

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
    c = Category(name="Books")
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def seller(client, users, cat):
    login(client, "seller@t.test")
    return users["seller"]


def form_data(cat, **over):
    start = utcnow() + timedelta(hours=1)
    data = {
        "title": "Old Book", "category_id": cat.id, "description": "A very old and rare book.",
        "starting_price": "500", "auction_start": start.strftime(FMT),
        "auction_end": (start + timedelta(days=2)).strftime(FMT),
        "images": [img()],
    }
    data.update(over)
    return data


def post_new(client, cat, **over):
    return client.post("/seller/products/new", data=form_data(cat, **over), content_type="multipart/form-data")


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


# ---- create -------------------------------------------------------------
def test_create_product_success(client, seller, cat, app):
    r = post_new(client, cat, images=[img("one.png"), img("two.jpg", "JPEG")])
    assert r.status_code == 302
    p = Product.query.one()
    assert p.seller_id == seller.id and p.approval_status == "pending"
    assert p.starting_price == Decimal("500") and len(p.images) == 2
    for i in p.images:
        assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], i.path))
        assert "one" not in i.path  # user-supplied name is never reused


def test_create_requires_image(client, seller, cat):
    r = post_new(client, cat, images=[])
    assert r.status_code == 200 and b"at least one product image" in r.data
    assert Product.query.count() == 0


def test_create_rejects_too_many_images(client, seller, cat):
    r = post_new(client, cat, images=[img(f"{i}.png") for i in range(6)])
    assert b"at most 5" in r.data and Product.query.count() == 0


def test_upload_rejects_non_image_with_image_extension(client, seller, cat, app):
    fake = (io.BytesIO(b"<?php echo 1; ?>"), "shell.png")
    r = post_new(client, cat, images=[fake])
    assert b"not a valid image" in r.data and Product.query.count() == 0
    assert not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "products")) or \
        not os.listdir(os.path.join(app.config["UPLOAD_FOLDER"], "products"))


def test_upload_rejects_bad_extension_and_real_image_renamed(client, seller, cat):
    assert b"only JPG" in post_new(client, cat, images=[(img_bytes(), "x.exe")]).data
    assert b"only JPG" in post_new(client, cat, images=[(img_bytes(), "x.svg")]).data
    assert b"only JPG" in post_new(client, cat, images=[(img_bytes(), "noext")]).data
    assert Product.query.count() == 0


def test_upload_rejects_unsupported_format_even_if_named_png(client, seller, cat):
    r = post_new(client, cat, images=[(img_bytes("BMP"), "x.png")])
    assert b"unsupported image type" in r.data and Product.query.count() == 0


def test_upload_rejects_oversized_image(client, seller, cat, app):
    app.config["MAX_IMAGE_BYTES"] = 10
    r = post_new(client, cat, images=[img()])
    assert b"larger than" in r.data and Product.query.count() == 0


def test_one_bad_file_stores_nothing(client, seller, cat, app):
    post_new(client, cat, images=[img("ok.png"), (io.BytesIO(b"junk"), "bad.png")])
    folder = os.path.join(app.config["UPLOAD_FOLDER"], "products")
    assert Product.query.count() == 0
    assert not os.path.exists(folder) or not os.listdir(folder)


@pytest.mark.parametrize("over,msg", [
    ({"starting_price": "0"}, b"price"),
    ({"starting_price": "abc"}, b"price"),
    ({"title": "ab"}, b"Field must be between"),
    ({"description": "short"}, b"Field must be between"),
    ({"category_id": 9999}, b"valid choice"),
])
def test_create_validation(client, seller, cat, over, msg):
    r = post_new(client, cat, **over)
    assert r.status_code == 200 and msg in r.data and Product.query.count() == 0


def test_auction_time_rules(client, seller, cat):
    now = utcnow()
    past = (now - timedelta(days=1)).strftime(FMT)
    assert b"cannot be in the past" in post_new(client, cat, auction_start=past).data
    start = now + timedelta(hours=1)
    short = (start + timedelta(minutes=1)).strftime(FMT)
    assert b"at least 5 minutes" in post_new(client, cat, auction_start=start.strftime(FMT), auction_end=short).data
    long_ = (start + timedelta(days=31)).strftime(FMT)
    assert b"longer than 30 days" in post_new(client, cat, auction_start=start.strftime(FMT), auction_end=long_).data
    assert Product.query.count() == 0


def test_xss_in_title_is_escaped(client, seller, cat):
    post_new(client, cat, title="<script>alert(1)</script>")
    r = client.get("/seller/")
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
    assert client.post(f"/seller/products/{p.id}/edit", data=form_data(cat)).status_code == 404
    assert client.post(f"/seller/products/{p.id}/delete").status_code == 404
    assert db.session.get(Product, p.id) is not None


# ---- edit ---------------------------------------------------------------
def test_edit_updates_and_resubmits_approved_listing(client, seller, cat):
    start = utcnow() + timedelta(hours=2)
    p = make_product(seller, cat, approval_status="approved", auction={"start": start, "status": "scheduled"})
    r = client.post(f"/seller/products/{p.id}/edit",
                    data=form_data(cat, title="New Title", images=[]), content_type="multipart/form-data")
    assert r.status_code == 302
    db.session.expire_all()
    p = db.session.get(Product, p.id)
    assert p.title == "New Title" and p.approval_status == "pending"
    assert p.auction is None and Auction.query.count() == 0  # must be re-approved


def test_edit_get_prefills_form(client, seller, cat):
    p = make_product(seller, cat)
    r = client.get(f"/seller/products/{p.id}/edit")
    assert r.status_code == 200 and p.auction_start.strftime(FMT).encode() in r.data


def test_edit_image_add_and_remove(client, seller, cat, app):
    r = post_new(client, cat)
    p = Product.query.one()
    old = p.images[0]
    old_path = os.path.join(app.config["UPLOAD_FOLDER"], old.path)
    assert os.path.exists(old_path)
    # removing the only image without adding one is refused
    r = client.post(f"/seller/products/{p.id}/edit",
                    data={**form_data(cat, images=[]), "remove_image": str(old.id)},
                    content_type="multipart/form-data")
    assert b"at least one image" in r.data and os.path.exists(old_path)
    # replace it
    r = client.post(f"/seller/products/{p.id}/edit",
                    data={**form_data(cat, images=[img("new.png")]), "remove_image": str(old.id)},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    db.session.expire_all()
    p = db.session.get(Product, p.id)
    assert len(p.images) == 1 and p.images[0].id != old.id
    assert not os.path.exists(old_path)


def test_edit_cannot_remove_other_products_images(client, seller, cat):
    other = make_user("other@t.test", "seller")
    foreign = make_product(other, cat)
    mine = make_product(seller, cat)
    client.post(f"/seller/products/{mine.id}/edit",
                data={**form_data(cat, images=[img()]), "remove_image": str(foreign.images[0].id)},
                content_type="multipart/form-data")
    db.session.expire_all()
    assert db.session.get(Product, foreign.id).images  # untouched


def test_cannot_edit_or_delete_after_auction_starts(client, seller, cat):
    for status, start in [("active", utcnow() - timedelta(hours=1)), ("closed", utcnow() - timedelta(days=2)),
                          ("scheduled", utcnow() - timedelta(minutes=1))]:
        p = make_product(seller, cat, approval_status="approved", auction={"start": start, "status": status})
        assert client.get(f"/seller/products/{p.id}/edit").status_code == 302
        r = client.post(f"/seller/products/{p.id}/edit", data=form_data(cat, title="Hacked"),
                        content_type="multipart/form-data")
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
    post_new(client, cat)
    p = Product.query.one()
    path = os.path.join(app.config["UPLOAD_FOLDER"], p.images[0].path)
    assert os.path.exists(path)
    assert client.post(f"/seller/products/{p.id}/delete").status_code == 302
    assert Product.query.count() == 0 and ProductImage.query.count() == 0
    assert not os.path.exists(path)


def test_delete_requires_post(client, seller, cat):
    p = make_product(seller, cat)
    assert client.get(f"/seller/products/{p.id}/delete").status_code == 405


# ---- dashboard ----------------------------------------------------------
def test_dashboard_tabs_and_ownership(client, seller, cat, users):
    other = make_user("other@t.test", "seller")
    make_product(other, cat, title="NotMine")
    make_product(seller, cat, title="Pending One")
    make_product(seller, cat, title="Active One", approval_status="approved",
                 auction={"start": utcnow() - timedelta(hours=1), "status": "active"})
    make_product(seller, cat, title="Done One", approval_status="approved",
                 auction={"start": utcnow() - timedelta(days=3), "status": "closed"})

    def titles(tab):
        d = client.get(f"/seller/?tab={tab}").data
        return {t for t in ("Pending One", "Active One", "Done One", "NotMine") if t.encode() in d}

    assert titles("all") == {"Pending One", "Active One", "Done One"}
    assert titles("pending") == {"Pending One"}
    assert titles("active") == {"Active One"}
    assert titles("completed") == {"Done One"}
    assert client.get("/seller/?tab=bogus").status_code == 200


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
