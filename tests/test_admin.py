from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g

from app.extensions import db
from app.models import Bid, Category, Notification, Product, User, Winner, utcnow

from .conftest import login, make_user
from .test_listing_validation import card_type, complete_checklist, make_card  # noqa: F401  (card_type is a fixture)
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
ADMIN_GETS = ["/admin/", "/admin/products", "/admin/users", "/admin/products/1"]
ADMIN_POSTS = ["/admin/products/1/remove", "/admin/users/1/toggle-active"]


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


# ---- approval goes through card verification only ------------------------
def test_the_generic_approve_and_reject_routes_are_retired(client, admin, users, cat):
    p = make_product(users["seller"], cat)
    assert client.post(f"/admin/products/{p.id}/approve").status_code == 404
    assert client.post(f"/admin/products/{p.id}/reject", data={"reason": "Blurry photos"}).status_code == 404
    p = db.session.get(Product, p.id)
    assert p.approval_status == "pending" and p.auction is None


def test_a_pending_card_is_sent_to_its_checklist(client, admin, users, cat, card_type):
    p = make_card(users["seller"], cat, card_type, verified=False)
    v = p.collectible_verification
    html = client.get(f"/admin/products/{p.id}").data.decode()
    assert f'href="/admin/cards/verify/{v.id}"' in html
    assert "Approve" not in html and f'action="/admin/products/{p.id}/remove"' not in html
    r = client.post(f"/admin/products/{p.id}/remove", data={"reason": "Counterfeit goods"})
    assert r.location.endswith(f"/admin/cards/verify/{v.id}")
    assert db.session.get(Product, p.id).approval_status == "pending"


def test_card_decisions_notify_the_seller(client, admin, users, cat, card_type):
    p = make_card(users["seller"], cat, card_type, verified=False, asset=False)
    v = p.collectible_verification
    client.post(f"/admin/cards/verify/{v.id}/more-info",
                data={"info_request": "Better card images", "message": "Please add a photo of the back."})
    complete_checklist(client, v.id)
    client.post(f"/admin/cards/verify/{v.id}/approve", data={"approval_notes": "ok"})
    assert db.session.get(Product, p.id).approval_status == "approved"
    other = make_card(users["seller"], cat, card_type, verified=False, asset=False)
    client.post(f"/admin/cards/verify/{other.collectible_verification.id}/reject",
                data={"rejection_reason": "Other reason", "rejection_details": "The photos show a different card."})
    assert db.session.get(Product, other.id).approval_status == "rejected"
    assert notes(users["seller"]) == ["More information needed", "Card approved", "Card rejected"]


def test_a_plain_pending_listing_can_only_be_removed(client, admin, users, cat):
    p = make_product(users["seller"], cat)
    html = client.get(f"/admin/products/{p.id}").data.decode()
    assert "can no longer be approved" in html and f'action="/admin/products/{p.id}/remove"' in html
    client.post(f"/admin/products/{p.id}/remove", data={"reason": "Not a trading card"})
    p = db.session.get(Product, p.id)
    assert p.approval_status == "rejected" and p.auction is None
    assert "Listing removed" in notes(users["seller"])


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
def test_categories_cannot_be_managed(client, admin):
    assert client.get("/admin/categories").status_code == 404
    assert client.post("/admin/categories", data={"name": "Electronics"}).status_code == 404
    assert Category.query.filter_by(name="Electronics").count() == 0
    assert b"/admin/categories" not in client.get("/admin/").data


def test_only_categories_holding_cards_are_offered(client, users, cat, card_type):
    cards = Category(name="Trading Cards")
    db.session.add_all([cards, Category(name="Electronics")])
    db.session.commit()
    make_product(users["seller"], cat)  # a plain listing does not make its category a card category
    make_card(users["seller"], cards, card_type)
    for path in ("/", "/auctions/"):
        html = client.get(path).data.decode()
        assert "Trading Cards" in html, path
        assert "Electronics" not in html and "Books" not in html, path
