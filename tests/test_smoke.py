from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Auction, Category, Product, User, utcnow


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_home_empty(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"No Active Auctions" in r.data


def test_home_lists_active_auction(client):
    seller = User(name="S", email="s@t.test", role="seller")
    seller.set_password("x")
    cat = Category(name="Books")
    db.session.add_all([seller, cat])
    db.session.flush()
    end = utcnow() + timedelta(hours=1)
    p = Product(seller_id=seller.id, category_id=cat.id, title="Rare Book",
                description="d", starting_price=Decimal("100"), approval_status="approved",
                auction_start=utcnow(), auction_end=end)
    db.session.add(p)
    db.session.flush()
    db.session.add(Auction(product_id=p.id, start_time=utcnow(), end_time=end,
                           original_end_time=end, current_bid=Decimal("100"), status="active"))
    db.session.commit()
    assert b"Rare Book" in client.get("/").data


def test_password_is_hashed():
    u = User(name="A", email="a@t.test")
    u.set_password("secret123")
    assert u.password_hash != "secret123"
    assert u.check_password("secret123")
    assert not u.check_password("wrong")
