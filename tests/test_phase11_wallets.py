"""Phase 11: a wallet is linked to an account only by proving control of it.

  Linking by signature ............. link_*            (one-time message, the signer is recovered on the server)
  Attacks on the link .............. link_refuses_*    (another signer, a changed message, replay, expiry, wrong wallet)
  One account per wallet ........... one_account_*     (a database constraint; a proven owner displaces an unproven claim)
  Only proven wallets count ........ proven_*          (approval, minting, listing, authorizing the winner, My cards)
  Cards follow a newly proven wallet follow_*
  The local demo wallet signs too .. devwallet_*
  The schema change has a migration  migration_*
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eth_account import Account
from eth_account.messages import encode_defunct
from flask import g
from sqlalchemy.exc import IntegrityError
from web3 import Web3

from app.extensions import db
from app.models import User
from app.services import auction_validation_service as avs
from app.services import blockchain_minting_service as bm
from app.services import card_settlement_service as css
from app.services import wallet_service

from .conftest import make_user, prove_wallet
from .test_auction import client_for
from .test_card_settlement import s  # noqa: F401 (fixture)
from .test_crypto import local_app  # noqa: F401 (fixture)
from .test_listing_validation import CONTRACT, WALLET_A, cat, card_type, complete_checklist, make_card, seller  # noqa: F401
from .test_minting import chain, verified_asset  # noqa: F401 (fixture)
from .test_phase1_card_identity import static_dir  # noqa: F401 (fixture)
from .test_phase9_scenarios import submitted_card, switch

ROOT = Path(__file__).resolve().parent.parent
KEY, OTHER_KEY = "0x" + "4c" * 32, "0x" + "5d" * 32  # throwaway test keys
ADDRESS, OTHER = Account.from_key(KEY).address, Account.from_key(OTHER_KEY).address


def challenge(client, address):
    return client.post("/auth/wallet/challenge", json={"address": address})


def signed(message, key):
    return Web3.to_hex(Account.sign_message(encode_defunct(text=message), private_key=key).signature)


def verify(client, address, signature):
    return client.post("/auth/wallet/verify", json={"address": address, "signature": signature})


def fresh(user):
    db.session.expire_all()
    return db.session.get(User, user.id)


def start(client, email="buyer@t.test", address=ADDRESS):
    switch(client, email)
    return challenge(client, address).get_json()["message"]


# =================================== linking by signature ====================================================================
def test_link_a_wallet_by_signing_the_one_time_message(client, users):
    message = start(client, address=ADDRESS.lower())
    for part in (f"Wallet: {ADDRESS}", f"Account: #{users['buyer'].id}", "Site: localhost", "Nonce: ", "does not send a transaction"):
        assert part in message, part
    assert start(client) != message  # every message carries a new nonce
    message = start(client)
    r = verify(client, ADDRESS, signed(message, KEY))
    assert r.status_code == 200 and r.get_json() == {"ok": True, "wallet": ADDRESS}
    buyer = fresh(users["buyer"])
    assert buyer.verified_wallet == ADDRESS and buyer.wallet_verified_at is not None
    page = client.get("/auth/profile").get_data(as_text=True)
    assert ADDRESS in page and "Verified on" in page and "Wallet verified" in page


def test_link_needs_a_signed_in_user(client):
    for path in ("/auth/wallet/challenge", "/auth/wallet/verify", "/auth/wallet/remove"):
        r = client.post(path, json={})
        assert r.status_code == 302 and "/auth/login" in r.headers["Location"], path


def test_link_can_be_removed(client, users):
    switch(client, "buyer@t.test")
    assert prove_wallet(client, KEY).get_json()["ok"]
    assert client.post("/auth/wallet/remove").status_code == 302
    buyer = fresh(users["buyer"])
    assert buyer.wallet_address is None and buyer.wallet_verified_at is None


def test_link_the_profile_form_can_no_longer_set_a_wallet(client, users):
    switch(client, "buyer@t.test")
    r = client.post("/auth/profile", data={"name": "B", "phone": "9000000000", "address": "Somewhere", "wallet_address": ADDRESS})
    assert r.status_code == 302 and fresh(users["buyer"]).wallet_address is None
    page = client.get("/auth/profile").get_data(as_text=True)
    assert 'name="wallet_address"' not in page and 'id="wallet-verify"' in page and "js/wallet-verify.js" in page


# =================================== attacks on the link =====================================================================
def test_link_refuses_a_signature_from_another_wallet_and_uses_up_the_message(client, users):
    message = start(client)
    r = verify(client, ADDRESS, signed(message, OTHER_KEY))
    assert r.status_code == 403 and "not made by this wallet" in r.get_json()["error"]
    assert fresh(users["buyer"]).wallet_address is None
    r = verify(client, ADDRESS, signed(message, KEY))  # one attempt per message
    assert r.status_code == 400 and "new message" in r.get_json()["error"] and fresh(users["buyer"]).wallet_address is None


def test_link_refuses_a_signature_over_a_changed_message(client, users):
    message = start(client)
    r = verify(client, ADDRESS, signed(message.replace("Nonce: ", "Nonce: 0"), KEY))
    assert r.status_code == 403 and fresh(users["buyer"]).wallet_address is None


def test_link_refuses_a_replayed_signature(client, users):
    signature = signed(start(client), KEY)
    assert verify(client, ADDRESS, signature).status_code == 200
    assert verify(client, ADDRESS, signature).status_code == 400  # the message is gone
    challenge(client, ADDRESS)
    assert verify(client, ADDRESS, signature).status_code == 403  # and the old signature covers none of the new message


def test_link_refuses_an_expired_message(client, users):
    message = start(client)
    with client.session_transaction() as sess:
        pending = dict(sess[wallet_service.CHALLENGE_KEY])
        pending["issued"] -= wallet_service.CHALLENGE_TTL + 1
        sess[wallet_service.CHALLENGE_KEY] = pending
    r = verify(client, ADDRESS, signed(message, KEY))
    assert r.status_code == 400 and "expired" in r.get_json()["error"] and fresh(users["buyer"]).wallet_address is None


def test_link_refuses_a_message_made_for_another_wallet(client, users):
    message = start(client, address=OTHER)
    r = verify(client, ADDRESS, signed(message, KEY))
    assert r.status_code == 400 and "not the wallet the message was made for" in r.get_json()["error"]


def test_link_refuses_a_message_issued_to_someone_else(client, users):
    message = start(client)  # issued to the buyer
    switch(client, "seller@t.test")
    r = verify(client, ADDRESS, signed(message, KEY))
    assert r.status_code == 400 and fresh(users["seller"]).wallet_address is None and fresh(users["buyer"]).wallet_address is None


@pytest.mark.parametrize("address", ["", None, 12, ["0x"], "0x" + "ab" * 32, "abandon " * 11 + "about", "0x1234", "0x" + "0" * 40])
def test_link_refuses_anything_that_is_not_a_public_address(client, users, address):
    switch(client, "buyer@t.test")
    r = challenge(client, address)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    if isinstance(address, str) and len(address) > 20:
        assert address.strip() not in r.get_data(as_text=True)  # a pasted secret is never echoed


@pytest.mark.parametrize("signature", [None, "", "0x1234", "0x" + "zz" * 65, 12, "0x" + "00" * 65])
def test_link_refuses_malformed_signatures(client, users, signature):
    start(client)
    assert verify(client, ADDRESS, signature).status_code in (400, 403) and fresh(users["buyer"]).wallet_address is None


# =================================== one account per wallet ==================================================================
def test_one_account_per_wallet_a_proven_wallet_cannot_be_linked_again(client, users):
    switch(client, "buyer@t.test")
    assert prove_wallet(client, KEY).get_json()["ok"]
    switch(client, "seller@t.test")
    r = challenge(client, ADDRESS)
    assert r.status_code == 409 and "already linked to another account" in r.get_json()["error"]
    assert fresh(users["seller"]).wallet_address is None and fresh(users["buyer"]).verified_wallet == ADDRESS


def test_one_account_per_wallet_a_proven_owner_displaces_an_unproven_claim(client, users):
    users["seller"].wallet_address = ADDRESS  # typed in before wallets had to be proven
    db.session.commit()
    switch(client, "buyer@t.test")
    assert prove_wallet(client, KEY).get_json()["ok"]
    assert fresh(users["seller"]).wallet_address is None and fresh(users["buyer"]).verified_wallet == ADDRESS


def test_one_account_per_wallet_is_enforced_by_the_database(users):
    users["buyer"].link_wallet(ADDRESS)
    users["seller"].link_wallet(ADDRESS)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_an_address_set_any_other_way_does_not_count_as_proven(users):
    buyer = users["buyer"]
    buyer.link_wallet(ADDRESS)
    db.session.commit()
    buyer = fresh(buyer)
    buyer.wallet_address = ADDRESS  # the same address again, after a reload, keeps the proof
    db.session.commit()
    assert fresh(buyer).has_verified_wallet
    buyer = fresh(buyer)
    buyer.wallet_address = OTHER
    db.session.commit()
    buyer = fresh(buyer)
    assert buyer.wallet_address == OTHER and buyer.verified_wallet is None


# =================================== only proven wallets count ===============================================================
def test_proven_approval_registers_a_card_only_to_a_proven_wallet_and_then_follows_the_proof(app, client, users, cat, card_type, static_dir):
    app.config["COLLECTIBLE_CONTRACT_ADDRESS"] = CONTRACT
    users["seller"].wallet_address = ADDRESS  # on record, never proven
    db.session.commit()
    card = submitted_card(client, card_type)
    vid = card.product.collectible_verification.id
    switch(client, "admin@t.test")
    assert "No verified wallet" in client.get(f"/admin/cards/verify/{vid}").get_data(as_text=True)
    complete_checklist(client, vid)
    page = client.post(f"/admin/cards/verify/{vid}/approve", data={"approval_notes": "ok"}, follow_redirects=True).get_data(as_text=True)
    assert "has not verified a wallet yet" in page
    db.session.expire_all()
    assert card.product.collectible_verification.verification_status == "verified" and card.blockchain_asset is None

    switch(client, "seller@t.test")
    assert prove_wallet(client, KEY).get_json()["ok"]
    assert "registered to it" in client.get("/auth/profile").get_data(as_text=True)
    db.session.expire_all()
    asset = card.blockchain_asset
    assert asset is not None and asset.owner_wallet == ADDRESS and asset.status == "draft"
    switch(client, "admin@t.test")
    page = client.get(f"/admin/cards/verify/{vid}").get_data(as_text=True)
    assert ADDRESS in page and "(verified)" in page


def test_proven_minting_refuses_a_wallet_the_seller_has_not_proven(users, cat, card_type, chain):
    asset = verified_asset(users["seller"], cat, card_type, chain)
    users["seller"].wallet_verified_at = None  # the address is on record but was never proven
    db.session.commit()
    with pytest.raises(bm.MintError, match="has not proven control"):
        bm.initiate_mint(asset, chain.admin)
    users["seller"].link_wallet(chain.stranger)  # proven, but not the wallet the card would be minted to
    db.session.commit()
    with pytest.raises(bm.MintError, match="has not proven control"):
        bm.initiate_mint(asset, chain.admin)
    users["seller"].link_wallet(chain.seller_wallet)
    db.session.commit()
    assert bm.initiate_mint(asset, chain.admin)["tx"]["from"] == chain.admin


def test_proven_listing_needs_a_proven_wallet(users, seller, cat, card_type):
    users["seller"].wallet_verified_at = None
    db.session.commit()
    codes = avs.check_listing(make_card(users["seller"], cat, card_type)).codes()
    assert "SELLER_WALLET_UNVERIFIED" in codes and "SELLER_NOT_OWNER" not in codes
    users["seller"].link_wallet(WALLET_A)
    db.session.commit()
    assert "SELLER_WALLET_UNVERIFIED" not in avs.check_listing(make_card(users["seller"], cat, card_type, cert="77712345")).codes()


def test_proven_the_seller_cannot_authorize_a_winner_who_has_not_proven_a_wallet(users, chain, s):
    assert css.authorization_blockers(s.payment) is None
    users["buyer"].wallet_verified_at = None
    db.session.commit()
    assert "has not verified a wallet" in css.authorization_blockers(s.payment)
    users["buyer"].link_wallet(s.buyer_wallet)
    users["seller"].wallet_verified_at = None
    db.session.commit()
    assert "seller has not verified their wallet" in css.authorization_blockers(s.payment)


def test_proven_my_cards_only_trusts_a_proven_wallet(client, users, seller, cat, card_type):
    held = make_card(users["seller"], cat, card_type, status="minted", token_id=88, owner=ADDRESS)
    users["buyer"].wallet_address = ADDRESS  # typed, never proven
    db.session.commit()
    switch(client, "buyer@t.test")
    html = client.get("/buyer/cards").get_data(as_text=True)
    assert held.title not in html and 'id="wallet-needed"' in html
    users["buyer"].link_wallet(ADDRESS)
    db.session.commit()
    html = client.get("/buyer/cards").get_data(as_text=True)
    assert held.title in html and 'id="wallet-needed"' not in html


# =================================== records follow a newly proven wallet ====================================================
def test_follow_a_new_proven_wallet_moves_unminted_records_but_never_minted_tokens(client, users, seller, cat, card_type):
    draft = make_card(users["seller"], cat, card_type, owner=WALLET_A, status="draft")
    minted = make_card(users["seller"], cat, card_type, owner=WALLET_A, status="minted", token_id=5, cert="22223333")
    switch(client, "seller@t.test")
    assert prove_wallet(client, KEY).get_json()["ok"]
    db.session.expire_all()
    assert draft.collectible_card.blockchain_asset.owner_wallet == ADDRESS
    assert minted.collectible_card.blockchain_asset.owner_wallet == WALLET_A  # the chain decides who holds a minted token


# =================================== the local demo wallet ===================================================================
def test_devwallet_signs_the_link_message_as_the_demo_seller_wallet(local_app):
    app = local_app
    make_user("seller@t.test", "seller")
    accounts = app.extensions["local_chain_accounts"]
    c = client_for(app, "seller@t.test")
    address = c.get("/dev-wallet/account").get_json()["address"]
    assert address == accounts[2]  # sellers act as the demo seller wallet, buyers as the demo buyer wallet
    message = challenge(c, address).get_json()["message"]
    signature = c.post("/dev-wallet/sign", json={"message": "0x" + message.encode().hex(), "address": address}).get_json()["signature"]
    assert verify(c, address, signature).get_json()["ok"]
    assert User.query.filter_by(email="seller@t.test").one().verified_wallet == accounts[2]


def test_devwallet_signs_only_hex_text_and_only_with_its_own_account(local_app):
    app = local_app
    make_user("buyer@t.test")
    accounts = app.extensions["local_chain_accounts"]
    c = client_for(app, "buyer@t.test")
    hex_text = "0x" + "hello".encode().hex()
    assert c.post("/dev-wallet/sign", json={"message": hex_text, "address": accounts[2]}).status_code == 400  # not this user
    assert c.post("/dev-wallet/sign", json={"message": "hello", "address": accounts[1]}).status_code == 400  # not hex
    assert c.post("/dev-wallet/sign", json={"message": hex_text, "address": accounts[1]}).status_code == 200
    g.pop("_login_user", None)
    assert app.test_client().post("/dev-wallet/sign", json={}).status_code == 302  # sign-in required


def test_devwallet_is_absent_in_a_normal_deployment(client, users):
    switch(client, "seller@t.test")
    assert client.post("/dev-wallet/sign", json={}).status_code == 404


# =================================== the schema change has a migration =======================================================
MIGRATION = ROOT / "migrations" / "versions" / "h18walletproof01_wallet_proof_of_control.py"


def test_migration_adds_proof_time_and_one_account_per_wallet_and_drops_payout_wallet():
    spec = importlib.util.spec_from_file_location("h18", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, wallet_address VARCHAR(42), payout_wallet VARCHAR(42))"))
        conn.execute(sa.text("INSERT INTO users (wallet_address, payout_wallet) VALUES ('0xA', '0xP'), (NULL, NULL), (NULL, NULL)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        columns = {c["name"] for c in sa.inspect(conn).get_columns("users")}
        assert "wallet_verified_at" in columns and "payout_wallet" not in columns
        assert tuple(conn.execute(sa.text("SELECT wallet_address, wallet_verified_at FROM users ORDER BY id")).first()) == ("0xA", None)
        savepoint = conn.begin_nested()
        with pytest.raises(IntegrityError):
            conn.execute(sa.text("INSERT INTO users (wallet_address) VALUES ('0xA')"))
        savepoint.rollback()
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        columns = {c["name"] for c in sa.inspect(conn).get_columns("users")}
        assert "payout_wallet" in columns and "wallet_verified_at" not in columns
        conn.execute(sa.text("INSERT INTO users (wallet_address) VALUES ('0xA')"))  # no longer unique
