from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g

from app.extensions import db
from app.models import Auction, Bid, Category, Notification, Product, User, Winner, utcnow

from .conftest import login, make_user
from .test_seller import make_product


@pytest.fixture
def cat(app):
    c = Category(name="Books")
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def admin(client, users):
    login(client, "admin@t.test")
    return users["admin"]


def notes(user):
    return [n.title for n in Notification.query.filter_by(user_id=user.id).all()]


# ---- access --------------------------------------------------------------
ADMIN_GETS = ["/admin/", "/admin/products", "/admin/users", "/admin/categories", "/admin/products/1"]
ADMIN_POSTS = ["/admin/products/1/approve", "/admin/products/1/reject", "/admin/products/1/remove",
               "/admin/users/1/toggle-active", "/admin/categories", "/admin/categories/1/rename",
               "/admin/categories/1/delete"]


def test_admin_area_forbidden_to_other_roles(client, users):
    for role in ("buyer", "seller"):
        client.post("/auth/logout")
        login(client, f"{role}@t.test")
        for path in ADMIN_GETS:
            assert client.get(path).status_code == 403, path
        for path in ADMIN_POSTS:
            assert client.post(path).status_code == 403, path


def test_admin_area_requires_login(client):
    for path in ADMIN_GETS:
        assert client.get(path).status_code == 302
    for path in ADMIN_POSTS:
        assert client.post(path).status_code == 302


def test_dashboard_counts(client, admin, users, cat):
    make_product(users["seller"], cat)
    r = client.get("/admin/")
    assert r.status_code == 200 and b"Pending approvals" in r.data


def test_login_routes_admin_to_dashboard(client, users):
    r = login(client, "admin@t.test")
    assert r.location.endswith("/dashboard")
    assert client.get("/dashboard").location.endswith("/admin/")


# ---- approve -------------------------------------------------------------
def test_approve_creates_auction_and_notifies(client, admin, users, cat):
    p = make_product(users["seller"], cat)  # starts in 1h -> scheduled
    assert client.post(f"/admin/products/{p.id}/approve").status_code == 302
    db.session.expire_all()
    p = db.session.get(Product, p.id)
    a = p.auction
    assert p.approval_status == "approved"
    assert a.status == "scheduled" and a.start_time == p.auction_start
    assert a.end_time == a.original_end_time == p.auction_end
    assert a.current_bid == p.starting_price and a.extension_count == 0
    assert "Product approved" in notes(users["seller"])


def test_approve_starts_immediately_when_start_passed(client, admin, users, cat):
    p = make_product(users["seller"], cat)
    p.auction_start = utcnow() - timedelta(minutes=2)
    p.auction_end = utcnow() + timedelta(hours=1)
    db.session.commit()
    client.post(f"/admin/products/{p.id}/approve")
    assert db.session.get(Product, p.id).auction.status == "active"


def test_approve_refused_when_window_passed(client, admin, users, cat):
    p = make_product(users["seller"], cat)
    p.auction_start = utcnow() - timedelta(days=2)
    p.auction_end = utcnow() - timedelta(days=1)
    db.session.commit()
    client.post(f"/admin/products/{p.id}/approve")
    db.session.expire_all()
    p = db.session.get(Product, p.id)
    assert p.approval_status == "pending" and p.auction is None


def test_approve_twice_creates_one_auction(client, admin, users, cat):
    p = make_product(users["seller"], cat)
    client.post(f"/admin/products/{p.id}/approve")
    client.post(f"/admin/products/{p.id}/approve")
    assert Auction.query.count() == 1


def test_approve_unknown_product_404(client, admin):
    assert client.post("/admin/products/999/approve").status_code == 404


# ---- reject / resubmit ---------------------------------------------------
def test_reject_needs_reason(client, admin, users, cat):
    p = make_product(users["seller"], cat)
    client.post(f"/admin/products/{p.id}/reject", data={"reason": ""})
    client.post(f"/admin/products/{p.id}/reject", data={"reason": "no"})
    assert db.session.get(Product, p.id).approval_status == "pending"


def test_reject_then_seller_resubmits(client, admin, users, cat):
    p = make_product(users["seller"], cat)
    client.post(f"/admin/products/{p.id}/reject", data={"reason": "Blurry photos, please retake."})
    db.session.expire_all()
    p = db.session.get(Product, p.id)
    assert p.approval_status == "rejected" and "Blurry" in p.rejection_reason
    assert "Product rejected" in notes(users["seller"])

    client.post("/auth/logout")
    login(client, "seller@t.test")
    assert b"Blurry photos" in client.get(f"/seller/products/{p.id}").data
    # the edit form is covered in test_seller; here we check the resubmission bookkeeping directly
    p.approval_status, p.rejection_reason = "pending", None
    db.session.commit()
    client.post("/auth/logout")
    login(client, "admin@t.test")
    client.post(f"/admin/products/{p.id}/approve")
    assert db.session.get(Product, p.id).approval_status == "approved"


def test_cannot_approve_or_reject_rejected_listing(client, admin, users, cat):
    p = make_product(users["seller"], cat, approval_status="rejected")
    client.post(f"/admin/products/{p.id}/approve")
    assert db.session.get(Product, p.id).auction is None
    client.post(f"/admin/products/{p.id}/reject", data={"reason": "again again"})
    assert db.session.get(Product, p.id).rejection_reason is None


# ---- remove live listing --------------------------------------------------
def test_remove_live_listing_cancels_auction_and_notifies(client, admin, users, cat):
    p = make_product(users["seller"], cat, approval_status="approved",
                     auction={"start": utcnow() - timedelta(hours=1), "status": "active"})
    db.session.add(Bid(auction_id=p.auction.id, buyer_id=users["buyer"].id, amount=Decimal("150")))
    db.session.commit()
    client.post(f"/admin/products/{p.id}/remove", data={"reason": "Counterfeit goods"})
    db.session.expire_all()
    p = db.session.get(Product, p.id)
    assert p.approval_status == "rejected" and p.auction.status == "cancelled"
    assert "Auction cancelled" in notes(users["buyer"])
    assert "Listing removed" in notes(users["seller"])
    # a removed listing cannot be edited back to life by the seller
    assert not p.is_editable


def test_remove_requires_reason_and_refuses_closed(client, admin, users, cat):
    live = make_product(users["seller"], cat, approval_status="approved",
                        auction={"start": utcnow() - timedelta(hours=1), "status": "active"})
    client.post(f"/admin/products/{live.id}/remove", data={"reason": ""})
    assert db.session.get(Product, live.id).auction.status == "active"

    done = make_product(users["seller"], cat, approval_status="approved",
                        auction={"start": utcnow() - timedelta(days=3), "status": "closed"})
    db.session.add(Winner(auction_id=done.auction.id, buyer_id=users["buyer"].id, winning_amount=Decimal("1")))
    db.session.commit()
    client.post(f"/admin/products/{done.id}/remove", data={"reason": "Counterfeit goods"})
    db.session.expire_all()
    assert db.session.get(Product, done.id).auction.status == "closed"


# ---- product list --------------------------------------------------------
def test_product_list_filters_and_search(client, admin, users, cat):
    make_product(users["seller"], cat, title="Alpha Lamp")
    make_product(users["seller"], cat, title="Beta Vase", approval_status="approved")

    def titles(qs):
        d = client.get(f"/admin/products{qs}").data
        return {t for t in ("Alpha Lamp", "Beta Vase") if t.encode() in d}

    assert titles("") == {"Alpha Lamp"}  # defaults to pending
    assert titles("?status=approved") == {"Beta Vase"}
    assert titles("?status=all") == {"Alpha Lamp", "Beta Vase"}
    assert titles("?status=all&q=vase") == {"Beta Vase"}
    assert titles("?status=bogus") == {"Alpha Lamp"}
    assert titles("?status=all&q=%25") == set()  # user-typed % matches literally, not as a wildcard
    assert titles("?status=all&q=_lpha") == set()
    assert client.get("/admin/products?status=all&page=99").status_code == 200


# ---- users ---------------------------------------------------------------
def test_user_list_filter_and_search(client, admin, users):
    d = client.get("/admin/users?role=seller").data
    assert b"seller@t.test" in d and b"buyer@t.test" not in d
    d = client.get("/admin/users?q=BUYER").data
    assert b"buyer@t.test" in d and b"seller@t.test" not in d
    assert client.get("/admin/users?role=bogus").status_code == 200
    assert client.get("/admin/users?q=' OR 1=1 --").status_code == 200


def test_deactivate_blocks_login_and_kills_live_session(client, admin, users, app):
    buyer_client = app.test_client()
    login(buyer_client, "buyer@t.test")
    assert buyer_client.get("/auth/profile").status_code == 200

    g.pop("_login_user", None)  # (the fixture's shared context still holds the buyer's login; real requests start fresh)
    client.post(f"/admin/users/{users['buyer'].id}/toggle-active")
    assert not db.session.get(User, users["buyer"].id).is_active_user
    # The test fixture keeps one app context open, so Flask-Login's per-request user cache
    # would leak between requests; real requests each get a fresh one.
    g.pop("_login_user", None)
    assert buyer_client.get("/auth/profile").status_code == 302  # existing session ended
    assert b"Invalid email or password" in login(app.test_client(), "buyer@t.test").data

    g.pop("_login_user", None)
    client.post(f"/admin/users/{users['buyer'].id}/toggle-active")  # reactivate
    g.pop("_login_user", None)
    assert login(app.test_client(), "buyer@t.test").status_code == 302


def test_admin_cannot_deactivate_self(client, admin):
    client.post(f"/admin/users/{admin.id}/toggle-active")
    assert db.session.get(User, admin.id).is_active_user


def test_toggle_redirect_ignores_foreign_referrer(client, admin, users):
    r = client.post(f"/admin/users/{users['buyer'].id}/toggle-active", headers={"Referer": "https://evil.example/x"})
    assert r.location.endswith("/admin/users")


# ---- categories ----------------------------------------------------------
def test_category_add_duplicate_rename_delete(client, admin, cat):
    client.post("/admin/categories", data={"name": "Toys"})
    assert Category.query.filter_by(name="Toys").count() == 1
    r = client.post("/admin/categories", data={"name": "toys"})  # case-insensitive duplicate
    assert b"already exists" in r.data and Category.query.count() == 2
    assert b"at least" in client.post("/admin/categories", data={"name": "x"}).data or Category.query.count() == 2

    toys = Category.query.filter_by(name="Toys").one()
    client.post(f"/admin/categories/{toys.id}/rename", data={"name": "Games"})
    assert db.session.get(Category, toys.id).name == "Games"
    client.post(f"/admin/categories/{toys.id}/rename", data={"name": "books"})  # clashes with Books
    assert db.session.get(Category, toys.id).name == "Games"

    client.post(f"/admin/categories/{toys.id}/delete")
    assert db.session.get(Category, toys.id) is None


def test_category_with_products_cannot_be_deleted(client, admin, users, cat):
    make_product(users["seller"], cat)
    client.post(f"/admin/categories/{cat.id}/delete")
    assert db.session.get(Category, cat.id) is not None
