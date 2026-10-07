"""Phase 9: the scenarios from the test plan, driven through the real routes and a real in-process chain.

Where each scenario is covered (earlier phases hold the unit-level tests, this file holds the end-to-end ones):

  Duplicate card ........................ test_listing_validation (rules), here: duplicate_card_across_sellers
  Duplicate active auction .............. test_card_auction, here: duplicate_card_across_sellers
  Wrong owner / wrong wallet ............ test_listing_validation, test_card_settlement, here: wrong_wallet_*
  Invalid bid ........................... test_auction, here: invalid_bids_on_a_card_auction
  Auction expiration .................... test_auction, here: expiry_*
  Late bid extension .................... test_auction, here: last_minute_bid_*
  Failed crypto transaction ............. test_crypto, here: failed_crypto_*
  Wrong payment amount / wrong network .. test_crypto, test_card_settlement, here: wrong_*
  Unauthorized token transfer ........... test_card_settlement (sale rules), here: unauthorized_token_transfer_*
  Payment replay ........................ test_crypto, test_card_settlement, here: payment_replay_*
  Verification manipulation ............. here: verification_manipulation_*
  Seller self-verifies .................. here: self_verification_*
  Seller modifies verified details ...... here: seller_modifying_*, editing_a_card_under_review_*
  The whole journey (spec section 41) ... here: the_whole_journey

Defects these tests found are pinned by the same tests: exact wei in SQLite (wrong_amount_*), the search API limit
(the_card_search_api_*), cards without an estimate breaking the browse pages and authenticity claims on the home and
sign-in pages (verification_wording_*). Also covered: csrf_*, xss_*, card_form_* (uploads).
"""
import io
import os
import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image
from web3 import Web3

from app.extensions import db
from app.models import (Auction, Bid, BlockchainTransfer, CardVerificationHistory, CollectibleCard, CryptoPayment, Invoice, Payment,
                        Product, ProductImage, User, utcnow)
from app.services import auction_service
from app.services import auction_validation_service as avs
from app.services import blockchain_ownership_service as ownership
from app.services import card_status_service as status

from .conftest import login, make_user, prove_wallet
from .test_card_auction import create as create_auction_post, form as auction_form, ready_card
from .test_card_settlement import authorize_on_chain, jpost, pay, pay_url, prepare_payment, reverts_with, sale_url
from .test_listing_validation import CHECKS, WALLET_A, WALLET_B, cat, card_type, complete_checklist, make_card, seller  # noqa: F401 (fixtures)
from .test_minting import chain  # noqa: F401 (fixture)
from .test_phase1_card_identity import ID_RE, card_form, static_dir  # noqa: F401 (fixture)


def switch(client, email):
    client.post("/auth/logout")
    login(client, email)


def bid(client, auction_id, amount):
    return client.post(f"/auctions/{auction_id}/bid", data={"amount": amount}, headers={"Accept": "application/json"})


# =================================== the whole journey (spec section 41) ====================================================
def test_the_whole_journey(app, client, users, cat, card_type, chain, static_dir):
    """Submit, verify, mint, auction, bids, win, pay in crypto, ownership moves, MySQL agrees."""
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = True
    seller_user, buyer = users["seller"], users["buyer"]
    rival = make_user("rival@t.test", "buyer")

    # 0. everyone proves they control their wallet by signing the site one-time message (keys of the test chain)
    keys = chain.w3.provider.ethereum_tester.backend.account_keys
    for email, index in (("seller@t.test", 1), ("buyer@t.test", 3), ("rival@t.test", 4)):
        switch(client, email)
        assert prove_wallet(client, keys[index].to_bytes()).get_json()["ok"]
    db.session.expire_all()
    assert (seller_user.verified_wallet, buyer.verified_wallet) == (chain.seller_wallet, chain.w3.eth.accounts[3])

    # 1. the seller submits a graded Pokemon card
    switch(client, "seller@t.test")
    r = client.post("/seller/cards/new", content_type="multipart/form-data",
                    data=card_form(card_type, is_graded="y", grading_company="PSA", grade="PSA 9", certification_number="12345678"))
    assert r.status_code == 302
    card = CollectibleCard.query.one()
    assert ID_RE.match(card.platform_card_id) and card.blockchain_asset is None
    assert status.lifecycle_code(card) == "SUBMITTED_FOR_VERIFICATION"
    assert create_auction_post(client, card.product).status_code == 409  # it cannot be auctioned yet

    # 2. the admin verifies it; the platform registers a blockchain identity for the seller wallet
    switch(client, "admin@t.test")
    vid = card.product.collectible_verification.id
    assert client.get(f"/admin/cards/verify/{vid}").status_code == 200
    client.post(f"/admin/cards/verify/{vid}/approve", data={"approval_notes": "Skipped the checklist"})
    db.session.expire_all()
    assert card.product.collectible_verification.verification_status == "pending"  # not without the checklist
    complete_checklist(client, vid)
    client.post(f"/admin/cards/verify/{vid}/approve", data={"approval_notes": "Checked"})
    db.session.expire_all()
    assert card.product.collectible_verification.verification_status == "verified"
    assert card.blockchain_asset.owner_wallet == chain.seller_wallet and card.blockchain_asset.status == "draft"
    assert status.lifecycle_code(card) == "VERIFIED"

    # 3. the admin mints the token with the admin wallet (signed in MetaMask, verified on-chain by the server)
    asset = card.blockchain_asset
    prep = jpost(client, f"/admin/tokens/{asset.id}/mint/prepare", {"wallet_address": chain.admin}).get_json()
    assert jpost(client, f"/admin/tokens/{asset.id}/mint/submit", {"tx_hash": chain.send(prep["tx"])}).get_json()["ok"]
    assert jpost(client, f"/admin/tokens/{asset.id}/verify").get_json()["token_id"] == 1
    db.session.expire_all()
    assert card.blockchain_asset.status == "minted" and status.lifecycle_code(card) == "APPROVED_FOR_AUCTION"

    # 4. the seller lists it: the server checks verification, identity, ownership on-chain and duplicates
    switch(client, "seller@t.test")
    assert create_auction_post(client, card.product).status_code == 302
    auction = Auction.query.one()
    assert auction.status == "active" and status.lifecycle_code(card) == "ACTIVE_AUCTION"

    # 5. two buyers bid; a low bid and a bid by the seller are refused
    switch(client, "rival@t.test")
    assert bid(client, auction.id, "600").get_json()["ok"]
    switch(client, "buyer@t.test")
    assert bid(client, auction.id, "700").get_json()["ok"]
    assert bid(client, auction.id, "650").status_code == 400
    switch(client, "seller@t.test")
    assert bid(client, auction.id, "900").status_code in (400, 403)

    # 6. the auction ends: the highest bidder wins and owes the payment
    auction.end_time = utcnow() - timedelta(seconds=5)
    db.session.commit()
    assert auction_service.close_auction(auction.id)["winner_mask"]
    db.session.expire_all()
    assert auction.winner.buyer_id == buyer.id and auction.winner.winning_amount == Decimal("700")
    assert status.lifecycle_code(card) == "PAYMENT_PENDING"
    switch(client, "rival@t.test")
    assert bid(client, auction.id, "800").status_code == 400  # too late

    # 7. the seller authorizes the transfer, the winner pays: one transaction pays and moves the token
    s = SimpleNamespace(card=card, auction=auction, buyer_wallet=buyer.wallet_address, payment=auction.payment)
    authorize_on_chain(client, chain, s)
    seller_before = chain.w3.eth.get_balance(chain.seller_wallet)
    tx_hash = pay(client, chain, s)

    # 8. the chain, MySQL, the records and the pages all agree
    db.session.expire_all()
    payment = db.session.get(Payment, auction.payment.id)
    assert payment.payment_status == "successful" and payment.crypto.status == "confirmed"
    assert chain.contract.functions.ownerOf(1).call() == buyer.wallet_address
    assert chain.w3.eth.get_balance(chain.seller_wallet) - seller_before == payment.crypto.expected_wei
    asset = card.blockchain_asset
    assert (asset.owner_wallet, asset.previous_owner, asset.status) == (buyer.wallet_address, chain.seller_wallet, "transferred")
    (transfer,) = BlockchainTransfer.query.all()
    assert transfer.transaction_hash == tx_hash and transfer.auction_id == auction.id
    assert ownership.check_ownership_sync(asset).status == ownership.IN_SYNC
    assert Invoice.query.filter_by(payment_id=payment.id).count() == 1
    assert status.lifecycle_code(card) == "TRANSFERRED"
    assert "ALREADY_SOLD" in avs.check_listing(card.product).codes()  # it can never be listed again
    switch(client, "buyer@t.test")
    mine = client.get("/buyer/cards").get_data(as_text=True)
    assert card.card_name in mine and "Yours on the blockchain" in mine and tx_hash[:10] in mine
    public = client.get(f"/collectibles/card-verification/{card.platform_card_id}").get_data(as_text=True)
    assert buyer.wallet_address in public and "Ownership history" in public


# =================================== duplicates across sellers ===============================================================
def test_duplicate_card_across_sellers(client, users, seller, cat, card_type):
    """Two sellers register the same graded card: the second cannot list it while the first listing is live."""
    other = make_user("seller2@t.test", "seller")
    other.link_wallet(WALLET_B)
    db.session.commit()
    first = ready_card(users["seller"], cat, card_type, cert="55512345")
    second = ready_card(other, cat, card_type, cert="55512345", owner=WALLET_B)
    switch(client, "seller@t.test")
    assert create_auction_post(client, first).status_code == 302
    switch(client, "seller2@t.test")
    r = create_auction_post(client, second)
    assert r.status_code == 409 and "already in an active auction" in r.get_data(as_text=True)
    assert Auction.query.count() == 1 and second.auction is None
    switch(client, "admin@t.test")  # and the admin is told before deciding
    assert "admin-duplicates" in client.get(f"/admin/cards/verify/{second.collectible_verification.id}").get_data(as_text=True)


def test_duplicate_card_is_free_once_the_first_listing_is_gone_but_flagged(client, users, seller, cat, card_type):
    other = make_user("seller2@t.test", "seller")
    other.link_wallet(WALLET_B)
    db.session.commit()
    first = ready_card(users["seller"], cat, card_type, cert="66612345")
    second = ready_card(other, cat, card_type, cert="66612345", owner=WALLET_B)
    switch(client, "seller@t.test")
    create_auction_post(client, first)
    first.auction.status = "cancelled"  # an admin took the listing down
    db.session.commit()
    check = avs.check_listing(second)
    assert check.ok and "POTENTIAL_DUPLICATE" in {w.code for w in check.warnings}  # allowed, but flagged for the admin


# =================================== wrong owner and wrong wallet ============================================================
def test_wrong_wallet_a_seller_who_links_another_wallet_cannot_list(client, users, seller, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    users["seller"].link_wallet(WALLET_B)  # proven, but not the wallet the card is registered to
    db.session.commit()
    switch(client, "seller@t.test")
    r = create_auction_post(client, p)
    assert r.status_code == 409 and "not the registered owner" in r.get_data(as_text=True) and Auction.query.count() == 0


def test_wrong_wallet_removing_the_wallet_also_blocks_listing(client, users, seller, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    switch(client, "seller@t.test")
    assert client.post("/auth/wallet/remove").status_code == 302
    r = create_auction_post(client, p)
    assert r.status_code == 409 and "not connected a wallet" in r.get_data(as_text=True)


def test_wrong_wallet_a_private_key_offered_as_a_wallet_is_refused(client, users, seller):
    switch(client, "seller@t.test")
    before = users["seller"].wallet_address
    secret = "0x" + "ab" * 32  # 64 hex characters: looks like a private key
    r = client.post("/auth/wallet/challenge", json={"address": secret})
    assert r.status_code == 400 and "private key" in r.get_json()["error"] and ("ab" * 32) not in r.get_data(as_text=True)
    assert db.session.get(User, users["seller"].id).wallet_address == before


def test_wrong_wallet_after_the_auction_the_payout_must_still_go_to_the_registered_owner(client, users, cat, card_type, chain, seller):
    from .test_card_settlement import sold_card
    s = sold_card(users, cat, card_type, chain)
    switch(client, "seller@t.test")
    users["seller"].link_wallet(chain.stranger)  # the seller now holds another (proven) wallet
    db.session.commit()
    r = jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet})
    assert r.status_code == 409 and "no longer matches the registered owner" in r.get_json()["error"]
    assert CryptoPayment.query.count() == 0


def test_wrong_owner_a_buyer_cannot_list_a_card_that_is_not_theirs(client, users, seller, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    switch(client, "buyer@t.test")
    assert create_auction_post(client, p).status_code == 403  # buyers have no listing rights at all
    assert Auction.query.count() == 0


# =================================== invalid bids on a card auction ==========================================================
def live_card_auction(client, users, cat, card_type, **over):
    p = ready_card(users["seller"], cat, card_type)
    switch(client, "seller@t.test")
    assert create_auction_post(client, p, **over).status_code == 302
    return Auction.query.one()


@pytest.mark.parametrize("amount", ["", " ", "abc", "-5", "0", "0.00", "1e3", "nan", "inf", "100.123", "99999999999", "\u0663\u0660\u0660", "5 00"])
def test_invalid_bids_on_a_card_auction(client, users, seller, cat, card_type, amount):
    a = live_card_auction(client, users, cat, card_type)
    switch(client, "buyer@t.test")
    r = bid(client, a.id, amount)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert Bid.query.count() == 0 and db.session.get(Auction, a.id).current_bid == Decimal("500")


def test_a_bid_must_beat_the_current_bid_by_the_minimum_increment(client, users, seller, cat, card_type):
    a = live_card_auction(client, users, cat, card_type)
    make_user("rival@t.test", "buyer")
    switch(client, "rival@t.test")
    assert bid(client, a.id, "600").get_json()["ok"]
    switch(client, "buyer@t.test")
    for amount in ("600", "600.00", "599.99", "500"):
        assert bid(client, a.id, amount).status_code == 400, amount
    assert bid(client, a.id, "600.01").get_json()["ok"]
    assert Bid.query.count() == 2


def test_only_buyers_may_bid_and_not_anonymous_visitors(client, users, seller, cat, card_type):
    a = live_card_auction(client, users, cat, card_type)  # logged in as the seller
    assert bid(client, a.id, "600").status_code in (400, 403)
    switch(client, "admin@t.test")
    assert bid(client, a.id, "600").status_code in (400, 403)
    client.post("/auth/logout")
    assert client.post(f"/auctions/{a.id}/bid", data={"amount": "600"}).status_code == 302  # sent to log in
    assert Bid.query.count() == 0


def test_a_bid_cannot_forge_the_bidder_or_the_winner(client, users, seller, cat, card_type):
    a = live_card_auction(client, users, cat, card_type)
    rival = make_user("rival@t.test", "buyer")
    switch(client, "buyer@t.test")
    r = client.post(f"/auctions/{a.id}/bid", headers={"Accept": "application/json"},
                    data={"amount": "600", "buyer_id": rival.id, "highest_bidder_id": rival.id, "current_bid": "1", "status": "closed"})
    assert r.get_json()["ok"]
    db.session.expire_all()
    auction = db.session.get(Auction, a.id)
    assert auction.highest_bidder_id == users["buyer"].id and Bid.query.one().buyer_id == users["buyer"].id
    assert auction.current_bid == Decimal("600") and auction.status == "active"


def test_nobody_can_bid_before_the_start_or_after_the_end(client, users, seller, cat, card_type):
    soon = (utcnow() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    a = live_card_auction(client, users, cat, card_type, start_time=soon, duration_hours="24")
    assert a.status == "scheduled"
    switch(client, "buyer@t.test")
    assert bid(client, a.id, "600").status_code == 400
    a.status, a.start_time, a.end_time = "active", utcnow() - timedelta(hours=1), utcnow() - timedelta(seconds=2)
    db.session.commit()  # the scheduler has not closed it yet, but the time is up
    r = bid(client, a.id, "600")
    assert r.status_code == 400 and "ended" in r.get_json()["error"]
    assert Bid.query.count() == 0


# =================================== expiry and the last-minute extension =====================================================
def test_expiry_an_unsold_card_auction_ends_without_a_winner_and_cannot_be_reused(client, users, seller, cat, card_type):
    a = live_card_auction(client, users, cat, card_type)
    a.end_time = utcnow() - timedelta(seconds=1)
    db.session.commit()
    info = auction_service.close_auction(a.id)
    db.session.expire_all()
    assert info["winner_mask"] is None and Payment.query.count() == 0
    assert status.lifecycle_code(db.session.get(Auction, a.id).product.collectible_card) == "AUCTION_ENDED"
    create_auction_post(client, a.product)  # the card page explains that it already has an auction
    assert Auction.query.count() == 1


def test_last_minute_bid_extends_the_auction_by_two_minutes_and_closing_waits(client, users, seller, cat, card_type):
    a = live_card_auction(client, users, cat, card_type)
    original_end = utcnow() + timedelta(seconds=30)
    a.end_time = a.original_end_time = original_end
    db.session.commit()
    switch(client, "buyer@t.test")
    assert bid(client, a.id, "600").get_json()["ok"]
    db.session.expire_all()
    auction = db.session.get(Auction, a.id)
    assert auction.extension_count == 1 and auction.end_time == original_end + timedelta(seconds=120)
    assert auction_service.close_auction(a.id, now=original_end + timedelta(seconds=1)) is None  # not over yet
    assert auction_service.close_auction(a.id, now=auction.end_time + timedelta(seconds=1))["winner_mask"]


def test_an_early_bid_does_not_extend_the_auction(client, users, seller, cat, card_type):
    a = live_card_auction(client, users, cat, card_type)
    end = db.session.get(Auction, a.id).end_time
    switch(client, "buyer@t.test")
    bid(client, a.id, "600")
    db.session.expire_all()
    assert db.session.get(Auction, a.id).end_time == end and db.session.get(Auction, a.id).extension_count == 0


# =================================== failed crypto transactions on a card sale ===============================================
from web3.datastructures import AttributeDict  # noqa: E402

from app.services import blockchain_service as bc  # noqa: E402
from app.services.blockchain_service import CryptoError  # noqa: E402

from .test_card_settlement import Market, PRICE_WEI, as_buyer, s, sold_card  # noqa: E402,F401


def reload_payment(s):
    db.session.expire_all()
    return db.session.get(Payment, s.payment.id)


def submit_real_payment(client, chain, s):
    """The buyer signs the real settle() transaction and reports its hash, without any patching."""
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    tx_hash = chain.send(prepare_payment(client, s).get_json()["tx"])
    return tx_hash, jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": tx_hash})


def test_failed_crypto_a_reverted_transaction_fails_the_payment_and_moves_no_ownership_in_mysql(client, chain, s, monkeypatch):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    tx = prepare_payment(client, s).get_json()["tx"]
    tx_hash = chain.send(tx)
    real = chain.w3.eth.get_transaction_receipt
    monkeypatch.setattr(chain.w3.eth, "get_transaction_receipt", lambda h: AttributeDict({**real(h), "status": 0}))
    jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": tx_hash})
    payment = reload_payment(s)
    assert payment.payment_status == "failed" and "failed on the blockchain" in payment.failure_reason
    assert BlockchainTransfer.query.count() == 0 and Invoice.query.count() == 0
    assert (s.asset.owner_wallet, s.asset.status) == (chain.seller_wallet, "minted")


def test_failed_crypto_a_transaction_the_network_never_shows_is_failed_after_the_timeout(client, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    prepare_payment(client, s)
    assert jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": "0x" + "ab" * 32}).get_json()["ok"]
    payment = reload_payment(s)
    assert payment.payment_status == "pending" and payment.processing  # waiting for the network to see it
    bc.verify_payment(payment, now=utcnow() + timedelta(minutes=31))
    payment = reload_payment(s)
    assert payment.payment_status == "failed" and "never found" in payment.failure_reason


def test_failed_crypto_a_failed_attempt_leaves_the_sale_open_for_a_correct_retry(client, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    prepare_payment(client, s)
    jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": "0x" + "cd" * 32})
    bc.verify_payment(reload_payment(s), now=utcnow() + timedelta(minutes=31))
    assert reload_payment(s).payment_status == "failed"
    pay(client, chain, s)  # the authorization is still in place, so the real payment goes through
    assert reload_payment(s).payment_status == "successful"
    assert chain.contract.functions.ownerOf(1).call() == s.buyer_wallet


# =================================== wrong network and wrong amount ==========================================================
def test_wrong_network_a_node_on_another_chain_stops_authorization_and_payment_without_side_effects(app, client, chain, s):
    switch(client, "seller@t.test")
    app.config["CHAIN_ID"] = 1  # the configuration no longer matches the node
    r = jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet})
    assert r.status_code == 503 and "different network" in r.get_json()["error"]
    assert CryptoPayment.query.count() == 0
    app.config["CHAIN_ID"] = chain.w3.eth.chain_id
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    app.config["CHAIN_ID"] = 1
    r = prepare_payment(client, s)
    assert r.status_code == 503 and reload_payment(s).payment_status == "pending"


def test_wrong_network_a_transaction_from_another_chain_is_a_failed_payment(client, chain, s, monkeypatch):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    tx_hash = chain.send(prepare_payment(client, s).get_json()["tx"])
    real = chain.w3.eth.get_transaction
    monkeypatch.setattr(chain.w3.eth, "get_transaction", lambda h: AttributeDict({**real(h), "chainId": 1}))
    jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": tx_hash})
    payment = reload_payment(s)
    assert payment.payment_status == "failed" and "wrong network" in payment.failure_reason


def test_wrong_network_a_node_switch_while_waiting_is_an_error_not_a_verdict(app, client, chain, s):
    app.config["CONFIRMATIONS_REQUIRED"] = 5  # keep the payment pending
    tx_hash, _ = submit_real_payment(client, chain, s)
    payment = reload_payment(s)
    assert payment.payment_status == "pending"
    payment.crypto.chain_id = 1  # quoted for another network than the node now serves
    db.session.commit()
    with pytest.raises(CryptoError) as e:
        bc.verify_payment(reload_payment(s))
    assert e.value.status == 503 and reload_payment(s).payment_status == "pending"


def test_wrong_amount_a_settlement_that_does_not_match_the_quote_is_not_accepted(client, chain, s):
    authorize_on_chain(client, chain, s)
    row = CryptoPayment.query.one()
    row.expected_wei = int(row.expected_wei) + 1  # the quote on record disagrees with the price that was fixed on-chain
    db.session.commit()
    as_buyer(client)
    prep = prepare_payment(client, s)
    assert prep.status_code == 409 and "does not match the winning bid" in prep.get_json()["error"]  # refused before any money moves
    assert chain.contract.functions.ownerOf(1).call() == chain.seller_wallet


def test_wrong_amount_a_verification_amount_mismatch_flags_the_sale_and_never_adopts_the_owner(client, chain, s):
    tx_hash, _ = submit_real_payment(client, chain, s)  # the payment succeeded: now damage the record before re-checking
    assert reload_payment(s).payment_status == "successful"
    check = bc.recheck(reload_payment(s))
    assert check.status == "confirmed"
    row = reload_payment(s).crypto
    row.expected_wei = int(row.expected_wei) + 1
    db.session.commit()
    assert "Wrong amount" in bc.recheck(reload_payment(s)).reason  # the on-chain evidence no longer matches the record


# =================================== amounts must be stored exactly ============================================================
def test_wrong_amount_exact_wei_amounts_survive_the_database(app, client, users, cat, card_type, chain, seller):
    """A rate that does not divide evenly gives a quote no floating-point column can hold exactly."""
    app.config["INR_PER_ETH"] = Decimal("321543.21")
    s = sold_card(users, cat, card_type, chain)
    s.payment.amount = Decimal("250000.57")
    db.session.commit()
    wei, _, _ = bc.quote(Decimal("250000.57"))
    assert wei % 2**10 != 0 and wei > 2**53  # not representable as a float
    switch(client, "seller@t.test")
    prep = jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet}).get_json()
    assert prep["ok"] and prep["terms"]["wei"] == str(wei)
    db.session.expire_all()
    assert int(CryptoPayment.query.one().expected_wei) == wei  # exactly what the seller is asked to fix on-chain
    chain.send(prep["tx"])
    pay(client, chain, s)  # the buyer pays the exact price and the server accepts it
    db.session.expire_all()
    payment = db.session.get(Payment, s.payment.id)
    assert payment.payment_status == "successful" and int(payment.crypto.expected_wei) == wei
    assert chain.contract.functions.ownerOf(1).call() == s.buyer_wallet


def test_wrong_amount_the_exact_decimal_column_round_trips_every_value():
    import sqlalchemy as sa
    from app.models.payment import ExactDecimal
    meta = sa.MetaData()
    table = sa.Table("t", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("wei", ExactDecimal(38, 0)),
                     sa.Column("eth", ExactDecimal(38, 18)))
    engine = sa.create_engine("sqlite://")
    meta.create_all(engine)
    values = [(250000000000000000, "0.25"), (777502252341139470, "0.77750225234113947"), (123456789012345678901, "123.456789012345678901"),
              (1, "0.000000000000000001"), (0, "0")]
    with engine.begin() as c:
        for wei, eth in values:
            c.execute(table.insert().values(wei=wei, eth=Decimal(eth)))
        c.execute(table.insert().values(wei=None, eth=Decimal(1)))
        rows = c.execute(sa.select(table.c.wei, table.c.eth).order_by(table.c.id)).all()
    assert [(int(w), e) for (w, e), _ in zip(rows, values)] == [(w, Decimal(e).quantize(Decimal(1).scaleb(-18))) for w, e in values]
    assert rows[-1][0] is None


# =================================== unauthorized token transfers ============================================================
def test_unauthorized_token_transfer_strangers_and_the_platform_cannot_move_a_token(chain):
    m = Market(chain)
    for who in (m.other, chain.admin):  # a stranger, and the platform owner who minted it
        reverts_with("ERC721InsufficientApproval(address,uint256)",
                     lambda: m.c.functions.transferFrom(m.seller, who, m.token).transact({"from": who}))
        safe = m.c.get_function_by_signature("safeTransferFrom(address,address,uint256)")
        reverts_with("ERC721InsufficientApproval(address,uint256)", lambda: safe(m.seller, who, m.token).transact({"from": who}))
    assert m.owner() == m.seller


def test_unauthorized_token_transfer_nobody_can_approve_themselves_for_someone_elses_token(chain):
    m = Market(chain)
    reverts_with("ERC721InvalidApprover(address)", lambda: m.c.functions.approve(m.other, m.token).transact({"from": m.other}))
    assert m.c.functions.getApproved(m.token).call() == "0x" + "00" * 20
    m.c.functions.setApprovalForAll(m.other, True).transact({"from": m.other})  # approving for their own (empty) wallet
    assert m.c.functions.isApprovedForAll(m.seller, m.other).call() is False
    reverts_with("ERC721InsufficientApproval(address,uint256)",
                 lambda: m.c.functions.transferFrom(m.seller, m.other, m.token).transact({"from": m.other}))


def test_unauthorized_token_transfer_the_authorized_buyer_cannot_take_the_token_without_paying(chain):
    m = Market(chain)
    m.authorize(price=ETH_PRICE)
    assert m.c.functions.getApproved(m.token).call() == m.c.address  # only the contract may move it, and only through settle()
    reverts_with("ERC721InsufficientApproval(address,uint256)",
                 lambda: m.c.functions.transferFrom(m.seller, m.buyer, m.token).transact({"from": m.buyer}))
    assert m.owner() == m.seller


def test_unauthorized_token_transfer_the_owner_keeps_control_of_their_own_token(chain):
    m = Market(chain)
    m.c.functions.transferFrom(m.seller, m.other, m.token).transact({"from": m.seller})
    assert m.owner() == m.other  # the registry follows the chain: this is what the sync check flags


ETH_PRICE = 10**18


# =================================== payment replay ===========================================================================
def test_payment_replay_verifying_a_confirmed_payment_again_changes_nothing(client, users, chain, s):
    tx_hash = (lambda: (authorize_on_chain(client, chain, s), pay(client, chain, s))[1])()
    counts = lambda: (Invoice.query.count(), BlockchainTransfer.query.count(), CryptoPayment.query.count())  # noqa: E731
    before = counts()
    for _ in range(3):
        bc.verify_payment(reload_payment(s))
        db.session.commit()
    assert counts() == before == (1, 1, 1)
    assert reload_payment(s).payment_status == "successful" and reload_payment(s).crypto.transaction_hash == tx_hash


def test_payment_replay_the_same_hash_cannot_be_submitted_twice_or_to_a_finished_payment(client, chain, s):
    tx_hash = (lambda: (authorize_on_chain(client, chain, s), pay(client, chain, s))[1])()
    again = jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": tx_hash})
    assert again.status_code == 409 and again.get_json()["ok"] is False
    assert reload_payment(s).payment_status == "successful" and Invoice.query.count() == 1
    assert prepare_payment(client, s).status_code == 409


def test_payment_replay_a_settled_auction_cannot_be_authorized_or_paid_again(client, chain, s):
    authorize_on_chain(client, chain, s)
    pay(client, chain, s)
    reverts_with("AuctionAlreadySettled(uint256)", lambda: chain.contract.functions.authorizeSale(
        1, s.auction.id, chain.stranger, ETH_PRICE).transact({"from": s.buyer_wallet}))
    reverts_with("NoSale(uint256)", lambda: chain.contract.functions.settle(s.auction.id, 1).transact(
        {"from": s.buyer_wallet, "value": PRICE_WEI}))
    switch(client, "seller@t.test")
    assert jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet}).status_code == 409


# =================================== verification manipulation and self-verification =========================================
DECISIONS = {
    "approve": {"approval_notes": "Looks fine"},
    "reject": {"rejection_reason": "Other reason", "rejection_details": "Not acceptable to the platform."},
    "more-info": {"info_request": "Clarify condition", "message": "Please clarify the condition."},
    "checklist": {f"{k}_result": "verified" for k in CHECKS},
}


def submitted_card(client, card_type, who="seller@t.test", **over):
    """A card created through the real seller form, so it starts exactly where a seller would leave it."""
    switch(client, who)
    r = client.post("/seller/cards/new", content_type="multipart/form-data", data=card_form(card_type, **over))
    assert r.status_code == 302
    return CollectibleCard.query.order_by(CollectibleCard.id.desc()).first()


def assert_still_waiting(card):
    db.session.expire_all()
    v = card.product.collectible_verification
    assert (v.verification_status, v.verified_by, v.verification_date) == ("pending", None, None) and not v.photos_verified
    assert card.product.approval_status == "pending" and card.blockchain_asset is None
    assert CardVerificationHistory.query.count() == 0


@pytest.mark.parametrize("decision", sorted(DECISIONS))
@pytest.mark.parametrize("actor", ["anonymous", "buyer", "seller"])
def test_self_verification_only_an_admin_can_decide_a_card(client, users, cat, card_type, static_dir, actor, decision):
    """The card own seller is the obvious cheat: they must not be able to approve, reject or even tick the checklist."""
    card = submitted_card(client, card_type)
    vid = card.product.collectible_verification.id
    if actor == "anonymous":
        client.post("/auth/logout")
    else:
        switch(client, f"{actor}@t.test")
    r = client.post(f"/admin/cards/verify/{vid}/{decision}", data=DECISIONS[decision])
    assert r.status_code == (302 if actor == "anonymous" else 403)
    if actor == "anonymous":
        assert "/auth/login" in r.headers["Location"]
    else:
        assert client.get(f"/admin/cards/verify/{vid}").status_code == 403
    assert_still_waiting(card)


def test_self_verification_a_seller_cannot_touch_the_token_registry(client, users, seller, cat, card_type):
    asset = ready_card(users["seller"], cat, card_type).collectible_card.blockchain_asset
    before = (asset.status, asset.token_id, asset.owner_wallet)
    switch(client, "seller@t.test")
    assert client.get("/admin/tokens").status_code == 403
    for path in ("mint/prepare", "mint/submit", "verify", "reconcile"):
        assert jpost(client, f"/admin/tokens/{asset.id}/{path}", {"wallet_address": WALLET_A, "tx_hash": "0x" + "ab" * 32}).status_code == 403
    db.session.expire_all()
    assert (asset.status, asset.token_id, asset.owner_wallet) == before


def test_verification_manipulation_the_submission_form_cannot_set_its_own_verdict(client, users, cat, card_type, static_dir):
    card = submitted_card(client, card_type, verification_status="verified", approval_status="approved", status="verified",
                          platform_card_id="CARD-000999", verified_by=users["admin"].id, photos_verified="y", token_id="7",
                          owner_wallet=WALLET_A, duplicate_flag="")
    assert ID_RE.match(card.platform_card_id) and card.platform_card_id != "CARD-000999"
    assert_still_waiting(card)


def test_seller_modifying_verified_details_is_refused_on_every_route(client, users, seller, cat, card_type, static_dir):
    product = ready_card(users["seller"], cat, card_type)
    card = product.collectible_card
    snapshot = lambda: (card.card_name, card.card_number, card.condition, card.set_name, product.title,  # noqa: E731
                        product.starting_price, product.approval_status, card.product.collectible_verification.verification_status)
    before = snapshot()
    switch(client, "seller@t.test")

    def attempt(expected):
        edit = client.post(f"/seller/cards/{card.id}/edit", content_type="multipart/form-data",
                           data=card_form(card_type, card_name="Changed after review", card_number="999/999", condition="Mint"))
        assert edit.status_code == 302 and edit.headers["Location"].endswith(f"/seller/cards/{card.id}")
        assert client.get(f"/seller/cards/{card.id}/edit").status_code == 302
        generic = client.post(f"/seller/products/{product.id}/edit", data={
            "title": "Changed", "description": "x" * 30, "starting_price": "1", "category_id": cat.id})
        assert generic.status_code == 302 and generic.headers["Location"].endswith(f"/seller/cards/{card.id}")
        assert client.post(f"/seller/products/{product.id}/delete").status_code == 302
        db.session.expire_all()
        assert db.session.get(Product, product.id) is not None and snapshot() == expected

    attempt(before)  # once it is verified
    assert create_auction_post(client, product).status_code == 302
    before = snapshot()  # listing legitimately sets the starting price
    auction_before = (product.auction.id, product.auction.status, product.auction.current_bid, product.auction.end_time)
    attempt(before)  # and again while it is on auction
    assert (product.auction.id, product.auction.status, product.auction.current_bid, product.auction.end_time) == auction_before


def test_seller_modifying_someone_elses_card_is_forbidden(client, users, cat, card_type, static_dir):
    card = submitted_card(client, card_type)
    make_user("seller2@t.test", "seller")
    for who in ("seller2@t.test", "admin@t.test", "buyer@t.test"):
        switch(client, who)
        r = client.post(f"/seller/cards/{card.id}/edit", content_type="multipart/form-data", data=card_form(card_type, card_name="Stolen"))
        assert r.status_code == 403
    switch(client, "seller2@t.test")
    assert client.get(f"/seller/cards/{card.id}").status_code in (403, 404)
    db.session.expire_all()
    assert card.card_name == "Charizard"


def test_editing_a_card_under_review_resubmits_it_and_keeps_its_identity(client, users, cat, card_type, static_dir):
    card = submitted_card(client, card_type)
    vid, platform_id = card.product.collectible_verification.id, card.platform_card_id
    switch(client, "admin@t.test")
    client.post(f"/admin/cards/verify/{vid}/more-info", data=DECISIONS["more-info"])
    db.session.expire_all()
    assert card.product.collectible_verification.verification_status == "more_info_needed"
    switch(client, "seller@t.test")
    r = client.post(f"/seller/cards/{card.id}/edit", content_type="multipart/form-data", data=card_form(card_type, card_name="Charizard corrected"))
    assert r.status_code == 302
    db.session.expire_all()
    v = card.product.collectible_verification
    assert (card.card_name, v.verification_status, v.submission_count) == ("Charizard corrected", "pending", 2)
    assert card.platform_card_id == platform_id and card.blockchain_asset is None and card.product.approval_status == "pending"


# =================================== wording: Platform Verified, never authentic ============================================
OVERCLAIM = re.compile(r"100\s*%\s*(authentic|genuine|real)|authenticity verified|professional authentication|guaranteed (authentic|genuine)"
                       r"|certified authentic|verified seller|\bcertified\b", re.I)  # the platform reviews cards, it does not certify them


def test_verification_wording_no_card_page_claims_a_card_is_authentic(client, users, seller, cat, card_type):
    product = ready_card(users["seller"], cat, card_type)
    card, vid, asset = product.collectible_card, product.collectible_verification.id, product.collectible_card.blockchain_asset
    switch(client, "seller@t.test")
    assert create_auction_post(client, product).status_code == 302
    auction = Auction.query.one()
    anonymous = ["/", "/shop", "/auth/login", "/auth/register", "/cards/browse", f"/cards/{card.id}", f"/auctions/{auction.id}",
                 f"/collectibles/card-verification/{card.platform_card_id}", "/cards/search?q=Charizard"]
    signed_in = {"seller@t.test": ["/seller/collectibles", f"/seller/cards/{card.id}"],
                 "admin@t.test": ["/admin/cards/verify?status=verified", f"/admin/cards/verify/{vid}", f"/admin/tokens/{asset.id}"]}
    pages = {}
    client.post("/auth/logout")
    for path in anonymous:
        pages[path] = client.get(path)
    for who, paths in signed_in.items():
        switch(client, who)
        pages.update({p: client.get(p) for p in paths})
    for path, r in pages.items():
        assert r.status_code == 200, path
        found = OVERCLAIM.search(r.get_data(as_text=True))
        assert found is None, f"{path} says {found.group(0)!r}"
    public = pages[f"/collectibles/card-verification/{card.platform_card_id}"].get_data(as_text=True)
    assert "Platform Verified" in public and "does not guarantee card authenticity" in public
    assert "Platform verified" in pages[f"/auctions/{auction.id}"].get_data(as_text=True)
    for path in ("/shop", "/cards/browse", f"/cards/{card.id}", "/cards/search?q=Charizard"):  # a card with no estimate must not break the page
        assert "Not given" in pages[path].get_data(as_text=True), path


# =================================== the card search API ======================================================================
def test_the_card_search_api_clamps_its_limit_and_only_lists_approved_cards(client, users, seller, cat, card_type):
    for i in range(55):
        ready_card(users["seller"], cat, card_type, asset=False, cert=f"{70000000 + i}")
    hidden = make_card(users["seller"], cat, card_type, verified=False, asset=False)  # pending: must never be listed
    count = lambda query: client.get("/api/cards/search" + query).get_json()  # noqa: E731
    assert len(count("?q=Charizard")) == 10  # the default
    assert len(count("?q=Charizard&limit=1000000")) == 50  # the ceiling
    assert len(count("?q=Charizard&limit=-5")) == len(count("?q=Charizard&limit=0")) == 1
    assert len(count("?q=Charizard&limit=abc")) == 10
    assert count("?q=C") == [] and count("") == []  # too short to be a search
    rows = count("?q=Charizard&limit=50")
    assert hidden.title not in {r["name"] for r in rows}
    assert set(rows[0]) == {"id", "name", "type", "set", "value"}  # nothing about the seller or the wallet


# =================================== CSRF ======================================================================================
def strict_app():
    from app import create_app
    from app.config import TestConfig

    class Strict(TestConfig):
        WTF_CSRF_ENABLED = True

    return create_app(Strict)


def test_csrf_every_state_changing_route_refuses_a_request_without_a_token():
    app = strict_app()
    with app.app_context():
        db.create_all()
        client = app.test_client()
        offenders, unbuildable, checked = [], [], 0
        for rule in app.url_map.iter_rules():
            methods = rule.methods & {"POST", "PUT", "PATCH", "DELETE"}
            if not methods:
                continue
            url = None
            for value in (1, "x"):
                try:
                    url = rule.build({a: value for a in rule.arguments})[1]
                    break
                except Exception:  # noqa: BLE001 - a converter that rejects this value
                    continue
            if url is None:
                unbuildable.append(rule.rule)
                continue
            for method in sorted(methods):
                checked += 1
                status = client.open(url, method=method, json={}).status_code
                if status != 400:
                    offenders.append((method, rule.rule, status))
        db.drop_all()
    assert unbuildable == [] and offenders == [] and checked >= 40, (unbuildable, offenders, checked)


def test_csrf_a_token_in_the_header_works_for_json_and_one_from_another_session_does_not():
    """Requests are made outside any app context on purpose: inside one, flask.g would hand every client the same token."""
    from .conftest import PASSWORD
    app = strict_app()
    with app.app_context():
        db.create_all()
        make_user("buyer@t.test", "buyer")
    token = lambda c: re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").get_data(as_text=True)).group(1)  # noqa: E731
    client, stranger = app.test_client(), app.test_client()
    assert client.post("/auth/login", data={"email": "buyer@t.test", "password": PASSWORD, "csrf_token": token(client)}).status_code == 302
    path = "/payments/1/crypto/prepare"
    own, other = token(client), token(stranger)
    assert own != other  # tokens are tied to a session
    assert client.post(path, json={}, headers={"X-CSRFToken": own}).status_code == 404  # accepted: it reached the view
    assert client.post(path, json={}, headers={"X-CSRFToken": other}).status_code == 400
    assert client.post(path, json={}, headers={"X-CSRFToken": "forged"}).status_code == 400
    assert client.post(path, json={}).status_code == 400
    with app.app_context():
        db.drop_all()


# =================================== stored XSS through card fields ==========================================================
XSS = ("<script>alert('p9xss')</script>", '"><img src=x onerror=alert(p9xss)>', "' onmouseover='alert(p9xss)")


@pytest.mark.parametrize("payload", XSS)
def test_xss_card_text_is_escaped_on_every_page_that_shows_it(client, users, seller, cat, card_type, payload):
    product = ready_card(users["seller"], cat, card_type)
    card = product.collectible_card
    for field in ("card_name", "set_name", "card_number", "manufacturer", "rarity", "edition", "condition_notes", "set_code", "language", "country"):
        setattr(card, field, payload)
    product.title = product.description = payload
    card.set_type_details({"pokemon_name": payload, "illustrator": payload, "holo_type": payload})
    db.session.commit()
    vid, asset_id = product.collectible_verification.id, card.blockchain_asset.id
    switch(client, "seller@t.test")

    def check(path, r):
        assert r.status_code == 200, path
        html = r.get_data(as_text=True)
        assert "<script>alert('p9xss')" not in html and "<img src=x onerror" not in html, path
        assert not re.search(r"""['"] onmouseover=['"]alert""", html), path
        return html

    shown = {}
    check("auction form", client.get(f"/seller/cards/{card.id}/auction"))  # only open while the card has no auction
    assert create_auction_post(client, product).status_code == 302
    auction = Auction.query.one()
    pages = {"seller@t.test": ["/seller/collectibles", f"/seller/cards/{card.id}"],
             "admin@t.test": ["/admin/cards/verify?status=verified", f"/admin/cards/verify/{vid}", "/admin/tokens", f"/admin/tokens/{asset_id}"],
             None: ["/", "/shop", "/cards/browse", f"/cards/{card.id}", "/cards/search?q=p9xss", f"/auctions/{auction.id}",
                    f"/collectibles/card-verification/{card.platform_card_id}"]}
    for who, paths in pages.items():
        client.post("/auth/logout") if who is None else switch(client, who)
        for path in paths:
            shown[path] = check(path, client.get(path))
    for path in (f"/cards/{card.id}", f"/collectibles/card-verification/{card.platform_card_id}", f"/auctions/{auction.id}"):
        assert "p9xss" in shown[path], path  # the text is displayed, as text
    api = client.get("/api/cards/search?q=p9xss")  # JSON: safe because of its type and nosniff, never HTML
    assert api.status_code == 200 and api.mimetype == "application/json" and api.headers["X-Content-Type-Options"] == "nosniff"


# =================================== the card form and uploaded files =========================================================
def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buf, "PNG")
    return buf.getvalue()


def upload_card(client, card_type, images):
    switch(client, "seller@t.test")
    return client.post("/seller/cards/new", content_type="multipart/form-data", data=card_form(card_type, card_images=images))


@pytest.mark.parametrize("name,data", [
    ("shell.php", png_bytes()), ("x.png.php", png_bytes()), ("x.svg", b"<svg onload=alert(1)></svg>"), ("x.png", b"<svg onload=alert(1)></svg>"),
    ("x.png", b"<?php system($_GET[0]); ?>"), ("x.html", b"<script>alert(1)</script>"), ("x.jpg", b""),
    ("x.png", b"\x89PNG\r\n\x1a\njunk"), ("x.exe", b"MZ\x90\x00"), ("noextension", png_bytes()),
])
def test_card_form_dangerous_or_fake_uploads_are_rejected_and_leave_nothing_behind(app, client, users, card_type, static_dir, name, data):
    r = upload_card(client, card_type, [(io.BytesIO(data), name)])
    assert r.status_code == 200 and CollectibleCard.query.count() == 0 and Product.query.count() == 0
    folder = os.path.join(app.config["UPLOAD_FOLDER"], "products")
    assert not os.path.exists(folder) or os.listdir(folder) == []


def test_card_form_accepts_at_most_ten_images_and_at_least_one(app, client, users, card_type, static_dir):
    too_many = upload_card(client, card_type, [(io.BytesIO(png_bytes()), f"{i}.png") for i in range(11)])
    none = upload_card(client, card_type, [])
    assert too_many.status_code == none.status_code == 200 and CollectibleCard.query.count() == 0
    assert b"at most 10" in too_many.data
    assert upload_card(client, card_type, [(io.BytesIO(png_bytes()), f"{i}.png") for i in range(10)]).status_code == 302
    assert ProductImage.query.count() == 10


def test_card_form_filenames_cannot_escape_the_upload_folder(app, client, users, card_type, static_dir):
    names = ("../../evil.png", "..\..\evil.png", "/etc/passwd.png", "shell.php.png", "x" * 300 + ".png")
    assert upload_card(client, card_type, [(io.BytesIO(png_bytes()), n) for n in names]).status_code == 302
    stored = [i.path for i in ProductImage.query.all()]
    assert len(stored) == len(names) and all(re.fullmatch(r"products/[0-9a-f]{32}\.png", p) for p in stored)
    root = app.config["UPLOAD_FOLDER"]
    assert set(os.listdir(os.path.join(root, "products"))) == {os.path.basename(p) for p in stored}
    assert not os.path.exists(os.path.join(os.path.dirname(root), "evil.png")) and not os.path.exists(os.path.join(root, "..", "evil.png"))
