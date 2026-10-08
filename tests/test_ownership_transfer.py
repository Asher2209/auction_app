"""Phase 7: after a settlement MySQL follows the chain; the history, the SOLD/TRANSFERRED states and reconciliation."""
from datetime import timedelta
from decimal import Decimal

import pytest
from web3 import Web3

from app.extensions import db
from app.models import Auction, BlockchainTransfer, Notification, Payment, Winner, utcnow
from app.services import auction_validation_service as avs
from app.services import blockchain_ownership_service as ownership
from app.services import blockchain_service as bc
from app.services import card_status_service as status
from app.services import ownership_transfer_service as ots
from app.services import payment_service

from .conftest import login
from .test_card_settlement import (PRICE_WEI, as_buyer, authorize_on_chain, jpost, pay, pay_url, prepare_payment,  # noqa: F401
                                   s, sold_card)
from .test_listing_validation import cat, card_type, make_card, seller  # noqa: E402,F401 (fixtures)
from .test_minting import chain  # noqa: F401 (fixture)


def sale(client, chain, s):
    authorize_on_chain(client, chain, s)
    return pay(client, chain, s)


def reload(s):
    db.session.expire_all()
    return db.session.get(type(s.asset), s.asset.id)


# ---- MySQL follows the chain ------------------------------------------------------------------------------------
def test_a_settlement_moves_the_owner_in_mysql_and_records_the_transfer(client, users, chain, s):
    tx_hash = sale(client, chain, s)
    asset = reload(s)
    payment = db.session.get(Payment, s.payment.id)
    assert (asset.owner_wallet, asset.previous_owner, asset.status) == (s.buyer_wallet, chain.seller_wallet, "transferred")
    (t,) = BlockchainTransfer.query.all()
    assert (t.from_wallet, t.to_wallet, t.auction_id, t.status) == (chain.seller_wallet, s.buyer_wallet, s.auction.id, "confirmed")
    assert t.transaction_hash == tx_hash == payment.crypto.transaction_hash
    assert t.block_number == payment.crypto.block_number and t.chain_id == chain.w3.eth.chain_id
    assert t.network == asset.blockchain_network and t.confirmed_at is not None
    assert ownership.check_ownership_sync(asset).status == ownership.IN_SYNC  # MySQL and the chain agree again
    assert "You now own the card token" in [n.title for n in Notification.query.filter_by(user_id=users["buyer"].id)]


def test_a_sold_card_can_not_be_listed_again(client, chain, s):
    sale(client, chain, s)
    assert "ALREADY_SOLD" in avs.check_listing(reload(s).collectible_card.product).codes()


def test_recording_a_settlement_twice_changes_nothing(client, users, chain, s):
    sale(client, chain, s)
    payment = db.session.get(Payment, s.payment.id)
    again = ots.record_settlement(payment, payment.crypto)
    db.session.commit()
    assert BlockchainTransfer.query.count() == 1 and again.id == BlockchainTransfer.query.one().id
    assert reload(s).owner_wallet == s.buyer_wallet and reload(s).previous_owner == chain.seller_wallet
    told = [n.title for n in Notification.query.filter_by(user_id=users["buyer"].id)]
    assert told.count("You now own the card token") == 1


def test_a_failed_payment_changes_no_ownership(client, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    prepare_payment(client, s)
    plain = Web3.to_hex(chain.w3.eth.send_transaction({"from": s.buyer_wallet, "to": chain.stranger, "value": 1}))
    jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": plain})
    asset = reload(s)
    assert (asset.owner_wallet, asset.status, asset.previous_owner) == (chain.seller_wallet, "minted", None)
    assert BlockchainTransfer.query.count() == 0
    assert status.lifecycle_code(asset.collectible_card) == "PAYMENT_PENDING"


def test_a_simulated_payment_marks_the_card_sold_but_does_not_invent_a_transfer(users, chain, s):
    payment_service.pay_simulated(s.auction.id, users["buyer"], "card",
                                  {"card_holder": "A Buyer", "card_number": "4242 4242 4242 4242", "expiry": "12/30", "cvv": "123"})
    db.session.expire_all()
    assert db.session.get(Payment, s.payment.id).payment_status == "successful"
    asset = reload(s)
    assert (asset.owner_wallet, asset.status) == (chain.seller_wallet, "minted")  # the token never moved
    assert BlockchainTransfer.query.count() == 0
    assert status.lifecycle_code(asset.collectible_card) == "SOLD"


# ---- the lifecycle state ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("verification, expected", [
    ("pending", "SUBMITTED_FOR_VERIFICATION"), ("under_review", "UNDER_ADMIN_REVIEW"),
    ("more_info_needed", "MORE_INFORMATION_REQUIRED"), ("rejected", "REJECTED")])
def test_lifecycle_before_verification(seller, cat, card_type, verification, expected):
    p = make_card(seller, cat, card_type, verified=False)
    p.collectible_verification.verification_status = verification
    db.session.commit()
    assert status.lifecycle_code(p.collectible_card) == expected


def test_lifecycle_after_verification(seller, cat, card_type):
    def code(**kw):
        return status.lifecycle_code(make_card(seller, cat, card_type, **kw).collectible_card)
    assert code(asset=False) == "VERIFIED"
    assert code() == "VERIFIED"  # registered, but the token is not minted yet
    p = make_card(seller, cat, card_type, status="minted", token_id=11)
    assert status.lifecycle_code(p.collectible_card) == "BLOCKCHAIN_REGISTERED"
    p.approval_status = "approved"
    db.session.commit()
    assert status.lifecycle_code(p.collectible_card) == "APPROVED_FOR_AUCTION"
    assert code(auction_status="scheduled") == "ACTIVE_AUCTION" and code(auction_status="active") == "ACTIVE_AUCTION"
    assert code(auction_status="closed") == "AUCTION_ENDED" and code(auction_status="cancelled") == "AUCTION_ENDED"
    assert code(status="transferred", token_id=12) == "TRANSFERRED"


def test_lifecycle_through_a_sale(client, chain, s):
    card = s.card
    assert status.lifecycle_code(card) == "PAYMENT_PENDING"
    sale(client, chain, s)
    assert status.lifecycle_code(reload(s).collectible_card) == "TRANSFERRED"
    assert status.lifecycle(reload(s).collectible_card) == {"code": "TRANSFERRED", "label": "Ownership transferred"}


# ---- what people see after a sale ------------------------------------------------------------------------------------
def public_page(client, s):
    client.post("/auth/logout")
    r = client.get(f"/collectibles/card-verification/{s.card.platform_card_id}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_the_public_card_page_shows_the_new_owner_and_the_history(client, chain, s):
    before = public_page(client, s)
    assert "Blockchain Identity" in before and "Ownership history" not in before and chain.seller_wallet in before
    sale(client, chain, s)
    after = public_page(client, s)
    assert "Blockchain Identity" in after  # the section must not vanish when the token changes hands
    assert s.buyer_wallet in after and "Ownership history" in after
    assert f"{s.buyer_wallet[:6]}...{s.buyer_wallet[-4:]}" in after and f"{chain.seller_wallet[:6]}...{chain.seller_wallet[-4:]}" in after


def test_the_buyer_sees_the_ownership_record_on_the_payment_page(client, chain, s):
    sale(client, chain, s)
    as_buyer(client)
    html = client.get(pay_url(s)).get_data(as_text=True)
    assert "Blockchain transaction" in html and "#1" in html and "ownership transferred" in html
    assert chain.seller_wallet in html and s.buyer_wallet in html


def test_the_seller_sees_the_card_as_transferred(client, chain, s):
    sale(client, chain, s)
    client.post("/auth/logout")
    login(client, "seller@t.test")
    html = client.get(f"/seller/cards/{s.card.id}").get_data(as_text=True)
    assert "Sold and paid." in html and "now belongs to the winner wallet" in html and "Ownership transferred" in html


def test_the_invoice_for_a_card_sale_still_downloads(client, chain, s):
    sale(client, chain, s)
    as_buyer(client)
    r = client.get(f"/invoices/{s.auction.id}/download")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")


# ---- reconciliation is explicit and admin-only -------------------------------------------------------------------------
def as_admin(client):
    client.post("/auth/logout")
    login(client, "admin@t.test")


def move_token(chain, to):
    """A transfer made outside the platform: the seller simply sends the token somewhere else."""
    return Web3.to_hex(chain.contract.functions.transferFrom(chain.seller_wallet, to, 1).transact({"from": chain.seller_wallet}))


def test_admin_pages_show_a_healthy_token_as_in_sync(client, users, chain, s):
    as_admin(client)
    assert "in sync" in client.get("/admin/tokens").get_data(as_text=True)
    detail = client.get(f"/admin/tokens/{s.asset.id}").get_data(as_text=True)
    assert "in sync" in detail and "Adopt the on-chain owner" not in detail


def test_a_token_moved_outside_the_platform_is_flagged_never_silently_adopted(client, users, chain, s):
    tx = move_token(chain, chain.stranger)
    as_admin(client)
    assert "SYNC ERROR" in client.get("/admin/tokens").get_data(as_text=True)
    detail = client.get(f"/admin/tokens/{s.asset.id}").get_data(as_text=True)
    assert "OWNERSHIP SYNC ERROR" in detail and "Adopt the on-chain owner" in detail and chain.stranger in detail
    assert reload(s).owner_wallet == chain.seller_wallet and BlockchainTransfer.query.count() == 0  # nothing changed yet

    r = client.post(f"/admin/tokens/{s.asset.id}/reconcile", follow_redirects=True)
    assert "now matches the blockchain" in r.get_data(as_text=True)
    asset = reload(s)
    assert (asset.owner_wallet, asset.previous_owner, asset.status) == (chain.stranger, chain.seller_wallet, "transferred")
    (t,) = BlockchainTransfer.query.all()
    assert (t.transaction_hash, t.from_wallet, t.to_wallet, t.auction_id) == (tx, chain.seller_wallet, chain.stranger, None)
    assert t.block_number == chain.w3.eth.get_transaction_receipt(tx)["blockNumber"]
    assert ownership.check_ownership_sync(asset).status == ownership.IN_SYNC
    assert "Ownership history" in client.get(f"/admin/tokens/{s.asset.id}").get_data(as_text=True)

    again = client.post(f"/admin/tokens/{s.asset.id}/reconcile", follow_redirects=True)
    assert "already in sync" in again.get_data(as_text=True) and BlockchainTransfer.query.count() == 1


def test_reconciling_is_admin_only(client, users, chain, s):
    move_token(chain, chain.stranger)
    url = f"/admin/tokens/{s.asset.id}/reconcile"
    assert client.post(url).status_code == 302
    for role in ("buyer", "seller"):
        client.post("/auth/logout")
        login(client, f"{role}@t.test")
        assert client.post(url).status_code == 403
    as_admin(client)
    assert client.post("/admin/tokens/9999/reconcile").status_code == 404
    assert reload(s).owner_wallet == chain.seller_wallet and BlockchainTransfer.query.count() == 0


def test_reconciling_without_a_blockchain_changes_nothing(app, client, users, chain, s):
    move_token(chain, chain.stranger)
    del app.extensions["web3"]
    as_admin(client)
    r = client.post(f"/admin/tokens/{s.asset.id}/reconcile", follow_redirects=True)
    assert "not configured" in r.get_data(as_text=True)
    assert reload(s).owner_wallet == chain.seller_wallet and BlockchainTransfer.query.count() == 0


def test_an_unminted_token_cannot_be_reconciled(client, users, cat, card_type, chain, seller):
    unminted = sold_card(users, cat, card_type, chain, minted=False)
    as_admin(client)
    r = client.post(f"/admin/tokens/{unminted.asset.id}/reconcile", follow_redirects=True)
    assert "Only a minted token can be reconciled" in r.get_data(as_text=True)


def test_a_sale_the_server_never_saw_is_repaired_and_then_confirmed_without_duplicates(client, users, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    tx_hash = chain.send(prepare_payment(client, s).get_json()["tx"])  # the buyer paid, but the browser never reported it
    assert reload(s).owner_wallet == chain.seller_wallet  # so MySQL is stale
    as_admin(client)
    client.post(f"/admin/tokens/{s.asset.id}/reconcile")
    assert reload(s).owner_wallet == s.buyer_wallet and BlockchainTransfer.query.one().auction_id is None

    as_buyer(client)  # the buyer finally reports the hash
    assert jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": tx_hash}).get_json()["ok"]
    db.session.expire_all()
    assert db.session.get(Payment, s.payment.id).payment_status == "successful"
    (t,) = BlockchainTransfer.query.all()  # still one record, now tied to the auction
    assert t.auction_id == s.auction.id and t.transaction_hash == tx_hash
    told = [n.title for n in Notification.query.filter_by(user_id=users["buyer"].id)]
    assert told.count("You now own the card token") == 1
