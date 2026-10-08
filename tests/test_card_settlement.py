"""Phase 6: atomic settlement. The buyer's single transaction pays the seller and receives the token, or reverts."""
import ast

import pytest
from eth_tester.exceptions import TransactionFailed
from web3 import Web3

from .test_minting import ARTIFACT, Chain, chain  # noqa: F401 (fixture)

ETH = 10**18


def reverts_with(signature, fn):
    """Run a transaction that must revert with the named custom error."""
    with pytest.raises(TransactionFailed) as e:
        fn()
    data = ast.literal_eval(str(e.value).split("execution reverted: ", 1)[1])
    assert data[:4] == Web3.keccak(text=signature)[:4], f"expected {signature}, got selector {data[:4].hex()}"


class Market:
    """Token 1 minted to the seller; a buyer and a bystander with test ETH."""

    def __init__(self, chain):
        self.chain, self.c, self.w3 = chain, chain.contract, chain.w3
        self.seller, self.buyer, self.other = chain.seller_wallet, self.w3.eth.accounts[3], self.w3.eth.accounts[4]
        self.c.functions.mint(self.seller, 7, b"\x01" * 32).transact({"from": chain.admin})
        self.token = 1

    def authorize(self, price=ETH, auction=1, buyer=None, sender=None):
        return self.c.functions.authorizeSale(self.token, auction, buyer or self.buyer, price).transact(
            {"from": sender or self.seller})

    def settle(self, value=ETH, auction=1, sender=None):
        return self.c.functions.settle(auction, self.token).transact({"from": sender or self.buyer, "value": value})

    def owner(self):
        return self.c.functions.ownerOf(self.token).call()

    def balance(self, who):
        return self.w3.eth.get_balance(who)


@pytest.fixture
def m(chain):
    return Market(chain)


def untouched(m, seller_balance):
    assert m.owner() == m.seller and m.balance(m.seller) == seller_balance


# ---- the honest sale -------------------------------------------------------------------------------------------
def test_settle_pays_the_seller_and_moves_the_token_in_one_transaction(m):
    m.authorize(price=3 * ETH)
    before = m.balance(m.seller)
    receipt = m.w3.eth.wait_for_transaction_receipt(m.settle(value=3 * ETH))
    assert m.owner() == m.buyer
    assert m.balance(m.seller) - before == 3 * ETH
    assert m.balance(m.c.address) == 0  # the contract never keeps funds
    event = m.c.events.CardSold().process_receipt(receipt)[0]["args"]
    assert (event.auctionId, event.tokenId, event.buyer, event.seller, event.amount) == (1, 1, m.buyer, m.seller, 3 * ETH)
    assert m.c.functions.auctionSettled(1).call() is True
    assert m.c.functions.sales(1).call()[0] == "0x" + "00" * 20  # sale consumed
    assert m.c.functions.getApproved(1).call() == "0x" + "00" * 20  # approval consumed


def test_authorizing_records_the_terms_and_approves_only_this_token(m):
    receipt = m.w3.eth.wait_for_transaction_receipt(m.authorize(price=2 * ETH, auction=5))
    assert m.c.functions.sales(1).call() == [m.seller, m.buyer, 2 * ETH, 5]
    assert m.c.functions.getApproved(1).call() == m.c.address
    event = m.c.events.SaleAuthorized().process_receipt(receipt)[0]["args"]
    assert (event.tokenId, event.auctionId, event.seller, event.buyer, event.price) == (1, 5, m.seller, m.buyer, 2 * ETH)


# ---- nobody can take the token for less, or at all ---------------------------------------------------------------
def test_buying_without_an_authorization_is_impossible_even_for_one_wei(m):
    before = m.balance(m.seller)
    reverts_with("NoSale(uint256)", lambda: m.settle(value=1))
    untouched(m, before)


@pytest.mark.parametrize("sent", [1, ETH - 1, ETH + 1, 2 * ETH])
def test_only_the_exact_price_is_accepted(m, sent):
    m.authorize(price=ETH)
    before = m.balance(m.seller)
    reverts_with("WrongPayment(uint256,uint256)", lambda: m.settle(value=sent))
    untouched(m, before)


def test_only_the_authorized_buyer_can_settle(m):
    m.authorize()
    before = m.balance(m.seller)
    reverts_with("NotTheBuyer()", lambda: m.settle(sender=m.other))
    untouched(m, before)


def test_the_payment_must_name_the_authorized_auction(m):
    m.authorize(auction=1)
    reverts_with("WrongAuction(uint256,uint256)", lambda: m.settle(auction=2))
    assert m.owner() == m.seller


def test_a_sale_cannot_be_replayed(m):
    m.authorize()
    m.settle()
    reverts_with("NoSale(uint256)", lambda: m.settle())  # the sale was consumed
    reverts_with("AuctionAlreadySettled(uint256)", lambda: m.authorize(sender=m.buyer, buyer=m.other))  # new owner, same auction
    assert m.owner() == m.buyer


def test_a_token_the_seller_moved_away_cannot_be_settled(m):
    m.authorize()
    m.c.functions.transferFrom(m.seller, m.other, m.token).transact({"from": m.seller})
    reverts_with("SellerNoLongerOwns(uint256)", lambda: m.settle())
    assert m.owner() == m.other


# ---- who may authorize -------------------------------------------------------------------------------------------
def test_only_the_token_owner_can_authorize_a_sale(m):
    reverts_with("NotTokenOwner(uint256)", lambda: m.authorize(sender=m.other))
    reverts_with("NotTokenOwner(uint256)", lambda: m.authorize(sender=m.chain.admin))  # the platform cannot force a sale


@pytest.mark.parametrize("buyer_is, price, error", [
    ("zero", ETH, "InvalidBuyer()"), ("seller", ETH, "InvalidBuyer()"), ("buyer", 0, "InvalidPrice()")])
def test_nonsense_terms_are_refused(m, buyer_is, price, error):
    buyer = {"zero": "0x" + "00" * 20, "seller": m.seller, "buyer": m.buyer}[buyer_is]
    reverts_with(error, lambda: m.authorize(price=price, buyer=buyer))


def test_authorizing_a_token_that_does_not_exist_fails(m):
    reverts_with("ERC721NonexistentToken(uint256)",
                 lambda: m.c.functions.authorizeSale(99, 1, m.buyer, ETH).transact({"from": m.seller}))


def test_the_seller_can_cancel_and_the_buyer_then_cannot_settle(m):
    m.authorize()
    reverts_with("NotTokenOwner(uint256)", lambda: m.c.functions.cancelSale(1).transact({"from": m.other}))
    m.c.functions.cancelSale(1).transact({"from": m.seller})
    assert m.c.functions.getApproved(1).call() == "0x" + "00" * 20
    reverts_with("NoSale(uint256)", lambda: m.settle())
    reverts_with("NoSale(uint256)", lambda: m.c.functions.cancelSale(1).transact({"from": m.seller}))


def test_new_terms_replace_the_old_ones(m):
    m.authorize(price=ETH)
    m.authorize(price=2 * ETH)
    reverts_with("WrongPayment(uint256,uint256)", lambda: m.settle(value=ETH))
    m.settle(value=2 * ETH)
    assert m.owner() == m.buyer


# =============================== the app around the contract ==================================================
from datetime import timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.extensions import db  # noqa: E402
from app.models import Auction, CryptoPayment, Invoice, Notification, Payment, Winner, utcnow  # noqa: E402
from app.services import blockchain_service as bc  # noqa: E402
from app.services import card_settlement_service as css  # noqa: E402

from .conftest import login, make_user  # noqa: E402
from .test_listing_validation import cat, card_type, make_card, seller  # noqa: E402,F401 (fixtures)
from .test_minting import mint_through_flow, verified_asset  # noqa: E402

PRICE_INR = Decimal("80000")  # 0.25 ETH at the default INR_PER_ETH of 320000
PRICE_WEI = 25 * 10**16


def sold_card(users, cat, card_type, chain, minted=True, winner_wallet=True):
    """A minted card whose auction has closed with a winner who owes the payment."""
    if winner_wallet:
        users["buyer"].link_wallet(chain.w3.eth.accounts[3])
    else:
        users["buyer"].unlink_wallet()
    db.session.commit()
    asset = verified_asset(users["seller"], cat, card_type, chain)
    product = asset.collectible_card.product
    product.approval_status = "approved"
    db.session.commit()
    if minted:
        mint_through_flow(asset, chain)
    now = utcnow()
    auction = Auction(product_id=product.id, start_time=now - timedelta(days=2), end_time=now - timedelta(days=1),
                      original_end_time=now - timedelta(days=1), current_bid=PRICE_INR,
                      highest_bidder_id=users["buyer"].id, status="closed")
    db.session.add(auction)
    db.session.commit()
    db.session.add(Winner(auction_id=auction.id, buyer_id=users["buyer"].id, winning_amount=PRICE_INR))
    payment = Payment(auction_id=auction.id, buyer_id=users["buyer"].id, amount=PRICE_INR, payment_status="pending")
    db.session.add(payment)
    db.session.commit()
    return SimpleNamespace(product=product, asset=asset, auction=auction, payment=payment, card=asset.collectible_card,
                           buyer_wallet=users["buyer"].wallet_address, seller_wallet=chain.seller_wallet)


@pytest.fixture
def s(users, cat, card_type, chain, seller):
    return sold_card(users, cat, card_type, chain)


def jpost(client, url, body=None):
    return client.post(url, json=body or {})


def sale_url(s, tail=""):
    return f"/seller/cards/{s.card.id}/sale{tail}"


def pay_url(s, tail=""):
    return f"/payments/{s.auction.id}{tail}"


def authorize_on_chain(client, chain, s):
    """The sale authorization step, exactly as the browser performs it."""
    client.post("/auth/logout")
    login(client, "seller@t.test")
    prep = jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet}).get_json()
    assert prep["ok"], prep
    chain.send(prep["tx"])
    return prep


# ---- the seller authorizes ------------------------------------------------------------------------------------------
def test_authorize_prepare_builds_the_owner_transaction_and_locks_the_quote(client, chain, s):
    login(client, "seller@t.test")
    prep = jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet}).get_json()
    assert prep["ok"] and prep["tx"]["from"] == chain.seller_wallet and prep["tx"]["to"] == chain.address
    assert prep["terms"] == {"token_id": 1, "buyer": s.buyer_wallet, "eth": "0.25", "wei": str(PRICE_WEI)}
    row = CryptoPayment.query.one()
    assert (row.wallet_address, row.seller_address, int(row.expected_wei)) == (s.buyer_wallet, chain.seller_wallet, PRICE_WEI)
    fn, args = chain.contract.decode_function_input(prep["tx"]["data"])
    assert fn.fn_name == "authorizeSale" and args == {"tokenId": 1, "auctionId": s.auction.id,
                                                      "buyer": s.buyer_wallet, "price": PRICE_WEI}


def test_only_the_wallet_that_owns_the_token_can_authorize(client, chain, s):
    login(client, "seller@t.test")
    for wallet in (chain.stranger, chain.admin, s.buyer_wallet):
        r = jpost(client, sale_url(s, "/prepare"), {"wallet_address": wallet})
        assert r.status_code == 403 and r.get_json()["ok"] is False
    for junk in ({}, {"wallet_address": 5}, {"wallet_address": "nope"}):
        assert jpost(client, sale_url(s, "/prepare"), junk).status_code == 400
    assert CryptoPayment.query.count() == 0


def test_authorization_is_refused_when_the_sale_cannot_go_ahead(client, users, cat, card_type, chain, seller):
    login(client, "seller@t.test")
    nowallet = sold_card(users, cat, card_type, chain, winner_wallet=False)
    r = jpost(client, sale_url(nowallet, "/prepare"), {"wallet_address": chain.seller_wallet})
    assert r.status_code == 409 and "has not verified a wallet" in r.get_json()["error"]
    unminted = sold_card(users, cat, card_type, chain, minted=False)
    r = jpost(client, sale_url(unminted, "/prepare"), {"wallet_address": chain.seller_wallet})
    assert r.status_code == 409 and "no minted blockchain token" in r.get_json()["error"]


def test_authorization_is_refused_if_the_token_is_no_longer_where_the_database_says(client, chain, s):
    chain.contract.functions.transferFrom(chain.seller_wallet, chain.stranger, 1).transact({"from": chain.seller_wallet})
    login(client, "seller@t.test")
    r = jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet})
    assert r.status_code == 409 and "OWNERSHIP SYNC ERROR" in r.get_json()["error"]


def test_authorization_is_refused_once_the_payment_is_under_way(client, chain, s):
    s.payment.payment_method, s.payment.payment_status = "crypto", "pending"
    db.session.commit()
    login(client, "seller@t.test")
    assert jpost(client, sale_url(s, "/prepare"), {"wallet_address": chain.seller_wallet}).status_code == 409


def test_sale_pages_belong_to_the_selling_seller_only(client, users, chain, s):
    assert client.get(sale_url(s)).status_code == 302
    login(client, "buyer@t.test")
    assert client.get(sale_url(s)).status_code == 403
    client.post("/auth/logout")
    make_user("other@t.test", "seller")
    login(client, "other@t.test")
    assert client.get(sale_url(s)).status_code == 404
    for tail in ("/prepare", "/check"):
        assert client.post(sale_url(s, tail), json={}).status_code == 404


def test_the_check_reads_the_chain_and_tells_the_winner_once(client, users, chain, s):
    login(client, "seller@t.test")
    assert jpost(client, sale_url(s, "/check")).get_json()["state"] == "missing"
    authorize_on_chain(client, chain, s)
    for _ in range(2):
        assert jpost(client, sale_url(s, "/check")).get_json() == {"ok": True, "state": "authorized", "reason": None}
    told = Notification.query.filter_by(user_id=users["buyer"].id, url=pay_url(s)).all()
    assert [n.title for n in told].count("The seller authorized the transfer: you can pay now") == 1


def test_terms_that_differ_from_the_winning_bid_are_reported_as_a_mismatch(client, chain, s):
    authorize_on_chain(client, chain, s)  # locks the quote
    chain.contract.functions.authorizeSale(1, s.auction.id, s.buyer_wallet, PRICE_WEI - 1).transact({"from": chain.seller_wallet})
    assert css.authorization_state(s.payment)["state"] == "mismatch"
    chain.contract.functions.authorizeSale(1, s.auction.id, chain.stranger, PRICE_WEI).transact({"from": chain.seller_wallet})
    assert css.authorization_state(s.payment)["state"] == "mismatch"


# ---- the winner pays -----------------------------------------------------------------------------------------------------
def as_buyer(client):
    client.post("/auth/logout")
    login(client, "buyer@t.test")


def prepare_payment(client, s, wallet=None):
    return jpost(client, pay_url(s, "/crypto/prepare"), {"accept_terms": True, "wallet_address": wallet or s.buyer_wallet})


def test_the_winner_cannot_pay_before_the_seller_authorizes(client, chain, s):
    as_buyer(client)
    r = prepare_payment(client, s)
    assert r.status_code == 409 and "has not authorized the transfer" in r.get_json()["error"]


def test_the_payment_transaction_is_a_settle_call_for_the_exact_price(client, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    prep = prepare_payment(client, s).get_json()
    assert prep["ok"] and prep["tx"]["to"] == chain.address and prep["tx"]["from"] == s.buyer_wallet
    assert int(prep["tx"]["value"], 16) == PRICE_WEI and prep["token_id"] == 1 and prep["seller_address"] == chain.seller_wallet
    fn, args = chain.contract.decode_function_input(prep["tx"]["data"])
    assert fn.fn_name == "settle" and args == {"auctionId": s.auction.id, "tokenId": 1}


def test_only_the_wallet_the_seller_authorized_can_be_used(client, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    r = prepare_payment(client, s, wallet=chain.stranger)
    assert r.status_code == 409 and "authorized this sale to the wallet" in r.get_json()["error"]


def test_other_users_cannot_touch_the_payment(client, chain, s):
    authorize_on_chain(client, chain, s)
    client.post("/auth/logout")
    make_user("rival@t.test", "buyer")
    login(client, "rival@t.test")
    assert prepare_payment(client, s).status_code == 404
    assert jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": "0x" + "ab" * 32}).status_code == 404


def pay(client, chain, s):
    as_buyer(client)
    prep = prepare_payment(client, s).get_json()
    tx_hash = chain.send(prep["tx"])
    assert jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": tx_hash}).get_json()["ok"]
    db.session.expire_all()
    return tx_hash


def test_the_whole_sale_through_the_routes(client, users, chain, s):
    authorize_on_chain(client, chain, s)
    seller_before = chain.w3.eth.get_balance(chain.seller_wallet)
    tx_hash = pay(client, chain, s)

    payment = db.session.get(Payment, s.payment.id)
    row = payment.crypto
    assert payment.payment_status == "successful" and payment.payment_method == "crypto"
    assert row.status == "confirmed" and row.transaction_hash == tx_hash and row.block_number and row.confirmations >= 1
    assert chain.contract.functions.ownerOf(1).call() == s.buyer_wallet  # the token moved in the same transaction
    assert chain.w3.eth.get_balance(chain.seller_wallet) - seller_before == PRICE_WEI  # and the seller was paid exactly
    assert chain.contract.functions.auctionSettled(s.auction.id).call() is True
    assert Invoice.query.filter_by(payment_id=payment.id).count() == 1
    assert "Payment received" in [n.title for n in Notification.query.filter_by(user_id=users["seller"].id)]


def test_a_second_payment_for_the_same_auction_is_impossible(client, chain, s):
    authorize_on_chain(client, chain, s)
    pay(client, chain, s)
    r = prepare_payment(client, s)
    assert r.status_code == 409
    reverts_with("NoSale(uint256)", lambda: chain.contract.functions.settle(s.auction.id, 1).transact(
        {"from": s.buyer_wallet, "value": PRICE_WEI}))


def test_the_poller_confirms_card_payments_without_the_payment_contract(app, client, chain, s):
    assert app.config["CONTRACT_ADDRESS"] is None  # only the token contract exists in this test
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    prep = bc.prepare(db.session.get(Payment, s.payment.id), s.buyer_wallet)
    bc.submit(db.session.get(Payment, s.payment.id), chain.send(prep["tx"]))
    assert bc.verify_pending() == 1
    assert db.session.get(Payment, s.payment.id).payment_status == "successful"


# ---- the chain is read, never believed ------------------------------------------------------------------------------------
def test_an_unrelated_transaction_does_not_pay_for_the_card(client, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    prepare_payment(client, s)
    plain = Web3.to_hex(chain.w3.eth.send_transaction({"from": s.buyer_wallet, "to": chain.stranger, "value": PRICE_WEI}))
    jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": plain})
    db.session.expire_all()
    payment = db.session.get(Payment, s.payment.id)
    assert payment.payment_status == "failed" and "not sent to the payment contract" in payment.failure_reason
    assert chain.contract.functions.ownerOf(1).call() == chain.seller_wallet


def test_a_failed_attempt_can_be_retried_with_the_real_settlement(client, chain, s):
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    prepare_payment(client, s)
    plain = Web3.to_hex(chain.w3.eth.send_transaction({"from": s.buyer_wallet, "to": chain.stranger, "value": 1}))
    jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": plain})
    pay(client, chain, s)
    assert db.session.get(Payment, s.payment.id).payment_status == "successful"
    assert chain.contract.functions.ownerOf(1).call() == s.buyer_wallet


def test_a_settlement_of_a_different_auction_cannot_pay_this_one(client, users, cat, card_type, chain, s):
    other = sold_card(users, cat, card_type, chain)
    authorize_on_chain(client, chain, s)
    authorize_on_chain(client, chain, other)
    as_buyer(client)
    prepare_payment(client, s)
    paid_other = chain.send(prepare_payment(client, other).get_json()["tx"])  # the buyer really buys the other card
    jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": paid_other})
    db.session.expire_all()
    first = db.session.get(Payment, s.payment.id)
    assert first.payment_status == "failed" and "does not contain a settlement for this auction" in first.failure_reason
    assert chain.contract.functions.ownerOf(1).call() == chain.seller_wallet  # this card is still the seller's


def test_a_transaction_hash_cannot_be_reused_for_another_payment(client, users, cat, card_type, chain, s):
    other = sold_card(users, cat, card_type, chain)
    authorize_on_chain(client, chain, s)
    authorize_on_chain(client, chain, other)
    used = pay(client, chain, s)
    as_buyer(client)
    prepare_payment(client, other)
    r = jpost(client, pay_url(other, "/crypto/submit"), {"tx_hash": used})
    assert r.status_code == 409 and "already been used" in r.get_json()["error"]


# ---- what people see ------------------------------------------------------------------------------------------------------------
def test_the_pay_page_waits_for_the_seller_then_offers_the_payment(client, chain, s):
    as_buyer(client)
    waiting = client.get(pay_url(s)).get_data(as_text=True)
    assert "has not authorized the transfer yet" in waiting and 'id="crypto-pay"' not in waiting
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    ready = client.get(pay_url(s)).get_data(as_text=True)
    assert 'id="crypto-pay"' in ready and "card token <strong>#1</strong>" in ready and s.buyer_wallet in ready
    assert "0.25 ETH" in ready and "has not authorized" not in ready


def test_the_pay_page_explains_why_crypto_is_unavailable_for_an_unminted_card(client, users, cat, card_type, chain, seller):
    unminted = sold_card(users, cat, card_type, chain, minted=False)
    as_buyer(client)
    html = client.get(pay_url(unminted)).get_data(as_text=True)
    assert "no minted blockchain token" in html and "Cryptocurrency (not configured)" in html
    assert 'id="crypto-pay"' not in html


def test_the_seller_pages_follow_the_sale(client, users, chain, s):
    login(client, "seller@t.test")
    card_page = f"/seller/cards/{s.card.id}"
    assert "Authorize transfer" in client.get(card_page).get_data(as_text=True)
    assert "Connect wallet" in client.get(sale_url(s)).get_data(as_text=True)
    authorize_on_chain(client, chain, s)
    assert "Authorized. The winner can now pay" in client.get(sale_url(s)).get_data(as_text=True)
    pay(client, chain, s)
    client.post("/auth/logout")
    login(client, "seller@t.test")
    assert "Sold and paid." in client.get(card_page).get_data(as_text=True)
    assert "sold and paid for" in client.get(sale_url(s)).get_data(as_text=True)


def test_the_sale_page_says_what_blocks_the_seller(client, users, cat, card_type, chain, seller):
    nowallet = sold_card(users, cat, card_type, chain, winner_wallet=False)
    login(client, "seller@t.test")
    html = client.get(sale_url(nowallet)).get_data(as_text=True)
    assert "has not verified a wallet" in html and "Authorize transfer</button>" not in html
