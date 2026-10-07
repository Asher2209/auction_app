"""Seller dashboard. /seller/ leads to My cards, which tells the seller whether their wallet is verified.

The older summary page (earnings and a typed-in payout wallet) was replaced by My cards. The card flow pays the token
owner, so the only wallet that matters is the one the seller has proven they control.
"""
from web3 import Web3

from app.extensions import db

from .conftest import login

ADDRESS = Web3.to_checksum_address("0x" + "12" * 20)


def test_the_seller_root_leads_to_my_cards(client, users):
    login(client, "seller@t.test")
    r = client.get("/seller/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/seller/collectibles")


def test_my_cards_shows_the_verified_wallet_shortened(client, users):
    users["seller"].link_wallet(ADDRESS)
    db.session.commit()
    login(client, "seller@t.test")
    html = client.get("/seller/collectibles").get_data(as_text=True)
    assert f"{ADDRESS[:6]}...{ADDRESS[-4:]}" in html and "(verified)" in html and "No verified wallet" not in html


def test_my_cards_asks_for_a_wallet_until_one_is_proven(client, users):
    login(client, "seller@t.test")
    html = client.get("/seller/collectibles").get_data(as_text=True)
    assert "No verified wallet" in html and "/auth/profile" in html
    users["seller"].wallet_address = ADDRESS  # an address that was never proven does not count
    db.session.commit()
    html = client.get("/seller/collectibles").get_data(as_text=True)
    assert "No verified wallet" in html and ADDRESS[:6] + "..." not in html
