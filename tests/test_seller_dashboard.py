"""Seller dashboard: stats, recent bids, earnings."""
from decimal import Decimal
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Auction, Bid, Category, Payment, Product, User

PASSWORD = "Test@1234"


def make_seller(app, email="seller@test.com", payout_wallet=None):
    """Create a seller user."""
    with app.app_context():
        u = User(name=email.split("@")[0], email=email, role="seller")
        u.set_password(PASSWORD)
        if payout_wallet:
            u.payout_wallet = payout_wallet
        db.session.add(u)
        db.session.commit()


def test_dashboard_payout_wallet_display(app, client):
    """Seller dashboard displays payout wallet address when set."""
    email = "seller@test.com"
    make_seller(app, email=email, payout_wallet="0x1234567890abcdef1234567890abcdef12345678")

    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    resp = client.get("/seller/")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    # Check that dashboard loaded and displays truncated wallet: first 6 chars and last 4
    assert "Seller Dashboard" in text
    assert "0x1234...5678" in text


def test_dashboard_payout_wallet_not_set(app, client):
    """Dashboard shows 'Not set' when payout wallet is missing."""
    email = "seller@test.com"
    make_seller(app, email=email)

    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    resp = client.get("/seller/")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Not set" in text


def test_dashboard_shows_summary_stats(app, client):
    """Dashboard displays summary statistics."""
    email = "seller@test.com"
    make_seller(app, email=email)

    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    resp = client.get("/seller/")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Active Auctions" in text
    assert "Pending Payout" in text
    assert "Total Earnings" in text
    assert "Payout Wallet" in text
