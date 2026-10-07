"""Crypto payments, tested against a real EVM (eth-tester, in-process) with the real compiled contract."""
import json
from collections import namedtuple
from datetime import timedelta
from decimal import Decimal

import pytest
import solcx
from flask import g
from hexbytes import HexBytes
from web3 import EthereumTesterProvider, Web3
from web3.datastructures import AttributeDict
from eth_tester.exceptions import TransactionFailed

from app import create_app
from app.config import TestConfig
from app.extensions import db, mail
from app.models import Category, CryptoPayment, Notification, Payment, User, utcnow
from app.services import blockchain_service as bc
from app.services import payment_service as ps

from .conftest import login, make_user
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_payments import client_for, titles, won

ART = json.load(open("contracts/build/AuctionPayment.json"))
Chain = namedtuple("Chain", "w3 contract deployer buyer seller other")
ETH = 10 ** 18


@pytest.fixture
def chain(app):
    w3 = Web3(EthereumTesterProvider())
    deployer, buyer, seller, other = w3.eth.accounts[:4]
    rc = w3.eth.wait_for_transaction_receipt(
        w3.eth.contract(abi=ART["abi"], bytecode=ART["bytecode"]).constructor().transact({"from": deployer}))
    app.extensions["web3"] = w3
    app.config.update(CONTRACT_ADDRESS=rc.contractAddress, CHAIN_ID=w3.eth.chain_id, CHAIN_NAME="Test chain",
                      CONFIRMATIONS_REQUIRED=2, BLOCK_EXPLORER_TX_URL="https://scan.test/tx/", INR_PER_ETH=Decimal("320000"))
    return Chain(w3, w3.eth.contract(address=rc.contractAddress, abi=ART["abi"]), deployer, buyer, seller, other)


@pytest.fixture
def setup(app, users, cats, chain):  # noqa: F811
    users["seller"].link_wallet(chain.seller)
    db.session.commit()
    a = won(users, cats, amount="80000")  # 80,000 INR = 0.25 ETH at the configured rate
    return a, client_for(app, "buyer@t.test"), chain


def mine(chain, n=1):
    chain.w3.provider.ethereum_tester.mine_blocks(n)


def prepare(c, a, chain, wallet=None):
    return c.post(f"/payments/{a.id}/crypto/prepare", json={"wallet_address": wallet or chain.buyer})


def send(chain, tx):
    h = chain.w3.eth.send_transaction({"from": tx["from"], "to": tx["to"], "value": int(tx["value"], 16), "data": tx["data"]})
    return chain.w3.to_hex(h)


def submit(c, a, h):
    return c.post(f"/payments/{a.id}/crypto/submit", json={"tx_hash": h})


def status(c, a):
    return c.get(f"/payments/{a.id}/status").json


def fresh(a):
    db.session.expire_all()
    return db.session.get(Payment, a.payment.id)


def pay_ok(c, a, chain):
    """prepare + send + submit through the real endpoints. Returns (prepare_json, tx_hash)."""
    prep = prepare(c, a, chain).json
    h = send(chain, prep["tx"])
    assert submit(c, a, h).json["ok"]
    return prep, h


# ---- wallet address handling ------------------------------------------------------------
ADDR = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"


def test_normalize_wallet_accepts_valid_forms():
    assert bc.normalize_wallet(ADDR) == ADDR
    assert bc.normalize_wallet(ADDR.lower()) == ADDR  # lower-case input is checksummed
    assert bc.normalize_wallet("0x" + ADDR[2:].upper()) == ADDR
    assert bc.normalize_wallet("  " + ADDR + "  ") == ADDR
    assert bc.normalize_wallet("") is None and bc.normalize_wallet(None) is None and bc.normalize_wallet("   ") is None


@pytest.mark.parametrize("bad", [
    ADDR.replace("5aAeb", "5AAeb"),                  # one letter's case flipped: wrong checksum
    ADDR[:30], ADDR + "00", "0x" + "g" * 40, ADDR[2:],  # wrong length / chars / missing 0x
    "0x" + "0" * 40,                                 # zero address
    "0x" + "ab" * 32, "ab" * 32,                     # 64 hex characters = a private key
    "abandon ability able about above absent absorb abstract absurd abuse access accident",  # seed phrase
    "<script>alert(1)</script>",
])
def test_normalize_wallet_rejects(bad):
    with pytest.raises(ValueError):
        bc.normalize_wallet(bad)


def test_a_wallet_is_offered_as_a_checksummed_address_and_secrets_are_never_echoed(app, users):
    c = client_for(app, "seller@t.test")
    r = c.post("/auth/wallet/challenge", json={"address": ADDR.lower()})
    assert r.status_code == 200 and f"Wallet: {ADDR}" in r.json["message"]  # what gets signed names the checksummed address
    secret = "0x" + "ab" * 32
    r = c.post("/auth/wallet/challenge", json={"address": secret})
    assert r.status_code == 400 and "private key or seed phrase" in r.json["error"] and ("ab" * 32) not in r.data.decode()
    assert db.session.get(User, users["seller"].id).wallet_address is None  # nothing is linked until a signature proves it


# ---- quote -------------------------------------------------------------------------------
def test_quote_example_from_the_brief(app):
    wei, eth, rate = bc.quote(Decimal("80000"))
    assert (wei, eth, rate) == (250000000000000000, Decimal("0.25"), Decimal("320000"))


def test_quote_rounds_up_so_the_seller_is_never_short(app):
    app.config["INR_PER_ETH"] = Decimal("300000")
    wei, eth, _ = bc.quote(Decimal("1"))
    assert wei == 3333333333334 and wei * 300000 >= 10 ** 18  # 1e18/300000 = 3333333333333.33...
    assert eth == Decimal(wei) / ETH


# ---- availability -----------------------------------------------------------------------
def test_crypto_is_off_without_a_chain(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    assert "Cryptocurrency (not configured)" in c.get(f"/payments/{a.id}").data.decode()
    r = prepare(c, a, type("X", (), {"buyer": ADDR}))
    assert r.status_code == 503 and r.json["ok"] is False


def test_crypto_tab_shows_quote_network_and_seller_wallet(app, setup):
    a, c, chain = setup
    html = c.get(f"/payments/{a.id}").data.decode()
    assert "0.25 ETH" in html and "320,000.00 per ETH" in html and "Test chain" in html and chain.seller in html
    assert "never sees your keys" in html and 'id="crypto-pay"' in html


def test_crypto_tab_explains_missing_seller_wallet(app, setup, users):
    a, c, chain = setup
    users["seller"].wallet_address = None
    db.session.commit()
    html = c.get(f"/payments/{a.id}").data.decode()
    assert "has not verified a wallet" in html and 'id="crypto-pay"' not in html
    r = prepare(c, a, chain)
    assert r.status_code == 409 and "has not verified a wallet" in r.json["error"]
    assert CryptoPayment.query.count() == 0


def test_crypto_never_pays_a_seller_wallet_that_was_not_proven(app, setup, users):
    a, c, chain = setup
    users["seller"].wallet_verified_at = None  # the address is on record, but its owner never signed for it
    db.session.commit()
    html = c.get(f"/payments/{a.id}").data.decode()
    assert "has not verified a wallet" in html and 'id="crypto-pay"' not in html
    r = prepare(c, a, chain)
    assert r.status_code == 409 and CryptoPayment.query.count() == 0


# ---- prepare ----------------------------------------------------------------------------
def test_prepare_builds_the_exact_transaction_and_locks_the_quote(app, setup):
    a, c, chain = setup
    j = prepare(c, a, chain).json
    assert j["ok"] and j["quote"] == {"inr": "80000.00", "eth": "0.25", "wei": str(ETH // 4), "rate": "320000.00"}
    assert j["chain"] == {"id": chain.w3.eth.chain_id, "id_hex": hex(chain.w3.eth.chain_id), "name": "Test chain"}
    tx = j["tx"]
    assert tx["from"] == chain.buyer and tx["to"] == chain.contract.address and int(tx["value"], 16) == ETH // 4
    selector = Web3.keccak(text="pay(uint256,address)")[:4].hex().removeprefix("0x")
    assert tx["data"].removeprefix("0x").startswith(selector)
    fn, args = chain.contract.decode_function_input(tx["data"])
    assert fn.fn_name == "pay" and args["auctionId"] == a.id and args["seller"] == chain.seller

    row = CryptoPayment.query.one()
    assert (row.wallet_address, row.seller_address, row.contract_address) == (chain.buyer, chain.seller, chain.contract.address)
    assert row.expected_wei == ETH // 4 and row.status == "pending" and row.transaction_hash is None
    p = fresh(a)  # preparing alone does not start the payment
    assert p.payment_method is None and p.awaiting_payment and p.attempts == 0


def test_prepare_ignores_anything_the_client_claims(app, setup):
    a, c, chain = setup
    j = c.post(f"/payments/{a.id}/crypto/prepare",
               json={"wallet_address": chain.buyer, "amount": "1", "wei": "1", "seller": chain.other}).json
    assert j["quote"]["wei"] == str(ETH // 4) and j["seller_address"] == chain.seller


def test_repeated_prepare_reuses_one_row_and_requotes(app, setup):
    a, c, chain = setup
    prepare(c, a, chain)
    app.config["INR_PER_ETH"] = Decimal("160000")
    j = prepare(c, a, chain).json
    assert j["quote"]["eth"] == "0.5" and CryptoPayment.query.count() == 1
    assert CryptoPayment.query.one().expected_wei == ETH // 2


@pytest.mark.parametrize("wallet,msg", [
    (ADDR.replace("5aAeb", "5AAeb"), "checksum"), ("nope", "valid address"), ("", "Connect your wallet"),
    (12345, "valid address"), ([ADDR], "valid address"), ({"a": 1}, "valid address"), (True, "valid address"),
    ("0x" + "ab" * 32, "private key or seed phrase"), ("0x" + "0" * 40, "zero address"), (None, "Connect your wallet"),
])
def test_prepare_rejects_bad_buyer_wallets(app, setup, wallet, msg):
    a, c, chain = setup
    r = c.post(f"/payments/{a.id}/crypto/prepare", json={"wallet_address": wallet})
    assert r.status_code == 400 and msg in r.json["error"] and CryptoPayment.query.count() == 0


def test_prepare_rejects_buyer_equal_to_seller_wallet(app, setup):
    a, c, chain = setup
    r = prepare(c, a, chain, wallet=chain.seller.lower())
    assert r.status_code == 400 and "must be different" in r.json["error"]


def test_prepare_garbage_bodies(app, setup):
    a, c, _ = setup
    for kw in ({"data": "not json", "content_type": "application/json"}, {"json": [1, 2]}, {"json": None}, {}):
        assert c.post(f"/payments/{a.id}/crypto/prepare", **kw).status_code in (400, 415)


def test_crypto_endpoints_access_control(app, setup, users):
    a, _, chain = setup
    make_user("other@t.test")
    for path in (f"/payments/{a.id}/crypto/prepare", f"/payments/{a.id}/crypto/submit"):
        g.pop("_login_user", None)
        assert app.test_client().post(path, json={}).status_code == 302
        for role in ("seller", "admin"):
            assert client_for(app, f"{role}@t.test").post(path, json={}).status_code == 403
        assert client_for(app, "other@t.test").post(path, json={"wallet_address": chain.other}).status_code == 404
        assert client_for(app, "buyer@t.test").get(path).status_code == 405


def test_crypto_endpoints_need_csrf_when_enabled(tmp_path):
    class Strict(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(Strict)
    with app.app_context():
        db.create_all()
        for path in ("prepare", "submit"):
            assert app.test_client().post(f"/payments/1/crypto/{path}", json={}).status_code == 400
        db.drop_all()


# ---- the happy path, end to end ------------------------------------------------------------
def test_full_payment_flow_with_confirmations(app, setup, users):
    a, c, chain = setup
    seller_before = chain.w3.eth.get_balance(chain.seller)
    prep = prepare(c, a, chain).json
    h = send(chain, prep["tx"])  # mined in 1 block
    with mail.record_messages() as outbox:
        assert submit(c, a, h).json == {"ok": True}
        p = fresh(a)
        assert (p.payment_method, p.payment_status, p.method_detail, p.attempts) == ("crypto", "pending", "eth", 1)
        assert p.processing and p.reference == f"ETH {chain.buyer[:6]}...{chain.buyer[-4:]}"
        row = p.crypto
        assert row.transaction_hash == h and row.confirmations == 1 and row.status == "pending"  # 1 of 2

        s = status(c, a)
        assert (s["status"], s["processing"], s["confirmations"], s["required"], s["tx_hash"]) == ("pending", True, 1, 2, h)
        page = c.get(f"/payments/{a.id}").data.decode()
        assert "Confirmations:" in page and f"https://scan.test/tx/{h}" in page and 'id="crypto-pay"' not in page
        assert outbox == []  # nothing is announced until the chain confirms it

        mine(chain)  # second confirmation
        s = status(c, a)
        assert (s["status"], s["processing"], s["confirmations"]) == ("successful", False, 2)

    p = fresh(a)
    assert p.payment_status == "successful" and p.payment_date and p.payment_method == "crypto"
    row = p.crypto
    assert (row.status, row.confirmations, row.transaction_hash) == ("confirmed", 2, h)
    assert row.amount == Decimal("0.25") and row.block_number and row.failure_reason is None
    assert chain.w3.eth.get_balance(chain.seller) - seller_before == ETH // 4  # the seller really got paid
    assert chain.w3.eth.get_balance(chain.contract.address) == 0  # the contract holds nothing
    assert "Payment successful" in titles(users["buyer"]) and "Payment received" in titles(users["seller"])
    assert sorted(m.subject for m in outbox) == ["[ChainBid] Payment received", "[ChainBid] Payment successful"]
    assert "Payment complete" in c.get(f"/payments/{a.id}").data.decode()


def test_verifying_again_is_a_no_op(app, setup):
    a, c, chain = setup
    pay_ok(c, a, chain)
    mine(chain)
    status(c, a)
    n = Notification.query.count()
    with mail.record_messages() as outbox:
        for _ in range(3):
            status(c, a)
            bc.verify_payment(fresh(a))
    assert outbox == [] and Notification.query.count() == n


def test_scheduler_confirms_without_the_page_open(app, setup):
    a, c, chain = setup
    pay_ok(c, a, chain)
    assert bc.verify_pending() == 1 and fresh(a).payment_status == "pending"  # 1 confirmation: not yet
    mine(chain)
    assert bc.verify_pending() == 1 and fresh(a).payment_status == "successful"
    assert bc.verify_pending() == 0  # nothing left to check


def test_admin_dashboard_counts_crypto_revenue(app, setup):
    a, c, chain = setup
    pay_ok(c, a, chain)
    mine(chain)
    status(c, a)
    assert ps.revenue_total() == Decimal("80000")
    assert "₹80,000.00" in client_for(app, "admin@t.test").get("/admin/").data.decode()


# ---- submit validation ----------------------------------------------------------------------
@pytest.mark.parametrize("h", ["", "0x123", "0x" + "g" * 64, "ab" * 32, "0x" + "ab" * 33, None, 5, "<b>"])
def test_submit_rejects_malformed_hashes(app, setup, h):
    a, c, chain = setup
    prepare(c, a, chain)
    r = submit(c, a, h)
    assert r.status_code == 400 and "valid transaction hash" in r.json["error"]
    assert fresh(a).payment_method is None


def test_submit_needs_a_prepared_payment(app, setup):
    a, c, chain = setup
    r = submit(c, a, "0x" + "ab" * 32)
    assert r.status_code == 409 and "Start the crypto payment first" in r.json["error"]


def test_submit_twice_for_one_attempt_is_refused(app, setup):
    a, c, chain = setup
    _, h = pay_ok(c, a, chain)
    r = submit(c, a, "0x" + "cd" * 32)
    assert r.status_code == 409 and fresh(a).crypto.transaction_hash == h


def test_a_transaction_hash_can_only_be_used_once(app, setup, users, cats):  # noqa: F811
    a, c, chain = setup
    _, h = pay_ok(c, a, chain)
    mine(chain)
    status(c, a)  # auction A is now paid with hash h
    # a second won auction by the same buyer: replaying A's hash must not work
    b = won_second(users, cats)
    prepare(c, b, chain)
    r = submit(c, b, h)
    assert r.status_code == 409 and "already been used" in r.json["error"]
    assert fresh(b).payment_method is None


def won_second(users, cats):  # noqa: F811
    from app.services import auction_service as svc
    b = make_auction(users["seller"], cats["Sports"], "Second item", 100)
    svc.place_bid(b.id, users["buyer"], "1000")
    svc.close_auction(b.id, now=b.end_time + timedelta(seconds=1))
    return b


# ---- verification failures ---------------------------------------------------------------
def failed(c, a, chain, reason_part):
    s = status(c, a)
    p = fresh(a)
    assert s["status"] == "failed" and reason_part in s["reason"], s
    assert p.payment_status == "failed" and p.crypto.status == "failed" and reason_part in p.crypto.failure_reason
    assert "Payment failed" in titles(p.buyer) and p.awaiting_payment  # the buyer may try again
    return p


def submit_raw(c, a, chain, h):
    """Register a hash for a prepared payment, then make it verifiable."""
    assert submit(c, a, h).json["ok"]
    mine(chain, 2)


def test_paying_someone_else_instead_of_the_contract_fails(app, setup):
    a, c, chain = setup
    tx = prepare(c, a, chain).json["tx"]
    h = chain.w3.to_hex(chain.w3.eth.send_transaction({"from": chain.buyer, "to": chain.other, "value": int(tx["value"], 16)}))
    submit_raw(c, a, chain, h)
    failed(c, a, chain, "not sent to the payment contract")


def test_a_different_sending_wallet_fails(app, setup):
    a, c, chain = setup
    tx = prepare(c, a, chain).json["tx"]
    h = chain.w3.to_hex(chain.w3.eth.send_transaction({**{k: tx[k] for k in ("to", "data")}, "from": chain.other, "value": int(tx["value"], 16)}))
    submit_raw(c, a, chain, h)
    failed(c, a, chain, "different wallet")


def test_underpayment_fails_with_both_amounts(app, setup):
    a, c, chain = setup
    prepare(c, a, chain)
    h = chain.w3.to_hex(chain.contract.functions.pay(a.id, chain.seller).transact({"from": chain.buyer, "value": ETH // 4 - 1}))
    submit_raw(c, a, chain, h)
    p = failed(c, a, chain, "Underpaid")
    assert "0.25" in p.crypto.failure_reason and "0.249999999999999999" in p.crypto.failure_reason


def test_overpayment_is_accepted_and_the_real_amount_recorded(app, setup):
    a, c, chain = setup
    prepare(c, a, chain)
    h = chain.w3.to_hex(chain.contract.functions.pay(a.id, chain.seller).transact({"from": chain.buyer, "value": ETH // 2}))
    submit_raw(c, a, chain, h)
    assert status(c, a)["status"] == "successful"
    assert fresh(a).crypto.amount == Decimal("0.5")


def test_wrong_seller_in_the_event_fails(app, setup):
    a, c, chain = setup
    prepare(c, a, chain)
    h = chain.w3.to_hex(chain.contract.functions.pay(a.id, chain.other).transact({"from": chain.buyer, "value": ETH // 4}))
    submit_raw(c, a, chain, h)
    failed(c, a, chain, "different seller address")


def test_payment_for_a_different_auction_fails(app, setup):
    a, c, chain = setup
    prepare(c, a, chain)
    h = chain.w3.to_hex(chain.contract.functions.pay(a.id + 100, chain.seller).transact({"from": chain.buyer, "value": ETH // 4}))
    submit_raw(c, a, chain, h)
    failed(c, a, chain, "does not contain a payment for this auction")


def test_borrowing_a_valid_payment_for_another_auction_fails(app, setup, users, cats):  # noqa: F811
    """A real, confirmed payment for auction B is not accepted as payment for auction A."""
    a, c, chain = setup
    b = won_second(users, cats)
    h = chain.w3.to_hex(chain.contract.functions.pay(b.id, chain.seller).transact({"from": chain.buyer, "value": ETH // 4}))
    prepare(c, a, chain)
    submit_raw(c, a, chain, h)
    failed(c, a, chain, "does not contain a payment for this auction")


def test_a_reverted_transaction_fails(app, setup, monkeypatch):
    a, c, chain = setup
    _, h = pay_ok(c, a, chain)
    mine(chain)
    real = chain.w3.eth.get_transaction_receipt
    monkeypatch.setattr(chain.w3.eth, "get_transaction_receipt", lambda x: AttributeDict({**real(x), "status": 0}))
    failed(c, a, chain, "failed on the blockchain")


def test_a_transaction_on_the_wrong_network_fails(app, setup, monkeypatch):
    a, c, chain = setup
    _, h = pay_ok(c, a, chain)
    real = chain.w3.eth.get_transaction
    monkeypatch.setattr(chain.w3.eth, "get_transaction", lambda x: AttributeDict({**real(x), "chainId": 1}))
    failed(c, a, chain, "wrong network")


def test_a_node_on_another_network_is_an_error_not_a_failed_payment(app, setup):
    a, c, chain = setup
    pay_ok(c, a, chain)
    CryptoPayment.query.one().chain_id = 999
    db.session.commit()
    s = status(c, a)
    assert s["status"] == "pending" and "different network" in s["error"]
    assert fresh(a).payment_status == "pending"


def test_unknown_transaction_waits_then_fails_after_the_timeout(app, setup):
    a, c, chain = setup
    prepare(c, a, chain)
    assert submit(c, a, "0x" + "ab" * 32).json["ok"]
    assert status(c, a)["status"] == "pending" and fresh(a).processing
    late = utcnow() + timedelta(minutes=app.config["CRYPTO_NOT_FOUND_TIMEOUT_MINUTES"] + 1)
    bc.verify_payment(fresh(a), now=late)
    assert fresh(a).payment_status == "failed" and "never found" in fresh(a).failure_reason


def test_contract_blocks_a_second_payment_for_an_auction_already_paid_on_chain(app, setup):
    """If calldata is tampered with (bypassing our UI) and the auction gets paid to the wrong address on
    chain, the app rejects that payment, and the contract will not take a second payment for the auction."""
    a, c, chain = setup
    prepare(c, a, chain)
    h = chain.w3.to_hex(chain.contract.functions.pay(a.id, chain.other).transact({"from": chain.buyer, "value": ETH // 4}))
    submit_raw(c, a, chain, h)
    failed(c, a, chain, "different seller address")
    with pytest.raises(TransactionFailed):
        chain.contract.functions.pay(a.id, chain.seller).transact({"from": chain.buyer, "value": ETH // 4})
    assert fresh(a).attempts == 1 and fresh(a).payment_status == "failed"


def test_failure_then_a_clean_second_attempt_succeeds(app, setup, users):
    a, c, chain = setup
    prepare(c, a, chain)
    bad = chain.w3.to_hex(chain.w3.eth.send_transaction({"from": chain.buyer, "to": chain.other, "value": 1}))
    submit_raw(c, a, chain, bad)
    failed(c, a, chain, "not sent to the payment contract")
    # retry: a fresh quote and a correct transaction
    prep = prepare(c, a, chain).json
    assert fresh(a).crypto.transaction_hash is None and fresh(a).crypto.status == "pending"
    good = send(chain, prep["tx"])
    assert submit(c, a, good).json["ok"]
    mine(chain)
    assert status(c, a)["status"] == "successful"
    p = fresh(a)
    assert p.attempts == 2 and p.crypto.transaction_hash == good and p.failure_reason is None


def test_crypto_and_simulated_payments_exclude_each_other(app, setup):
    a, c, chain = setup
    pay_ok(c, a, chain)  # crypto is now processing
    r = c.post(f"/payments/{a.id}/pay/upi", data={"upi_id": "bella@okbank"})
    assert fresh(a).method_detail == "eth" and fresh(a).attempts == 1 and r.status_code == 302
    assert prepare(c, a, chain).status_code == 409


def test_a_paid_auction_cannot_start_crypto_again(app, setup):
    a, c, chain = setup
    c.post(f"/payments/{a.id}/pay/upi", data={"upi_id": "bella@okbank"})
    assert fresh(a).payment_status == "successful"
    assert prepare(c, a, chain).status_code == 409 and CryptoPayment.query.count() == 0


# ---- outages ---------------------------------------------------------------------------------
def test_rpc_outage_keeps_the_payment_pending(app, setup, monkeypatch):
    a, c, chain = setup
    pay_ok(c, a, chain)

    def down(*a, **k):
        raise ConnectionError("node unreachable")

    monkeypatch.setattr(chain.w3.eth, "get_transaction", down)
    s = status(c, a)
    assert s["status"] == "pending" and s["processing"] and "Could not reach the blockchain" in s["error"]
    assert bc.verify_pending() == 0  # swallowed and logged, never raised
    assert fresh(a).payment_status == "pending"


# ---- the contract itself -----------------------------------------------------------------------
def test_contract_forwards_funds_emits_event_and_holds_nothing(chain):
    w3, k = chain.w3, chain.contract
    before = w3.eth.get_balance(chain.seller)
    rc = w3.eth.wait_for_transaction_receipt(k.functions.pay(7, chain.seller).transact({"from": chain.buyer, "value": ETH}))
    assert rc.status == 1 and w3.eth.get_balance(chain.seller) - before == ETH and w3.eth.get_balance(k.address) == 0
    ev = k.events.PaymentMade().process_receipt(rc)[0]["args"]
    assert (ev["auctionId"], ev["buyer"], ev["seller"], ev["amount"]) == (7, chain.buyer, chain.seller, ETH)
    assert k.functions.paid(7).call() is True and k.functions.paid(8).call() is False


@pytest.mark.parametrize("auction,seller,value", [(7, "seller", 1), (8, "seller", 0), (9, "zero", 1)])
def test_contract_refuses_bad_calls(chain, auction, seller, value):
    chain.contract.functions.pay(7, chain.seller).transact({"from": chain.buyer, "value": 1})  # auction 7 is paid
    target = chain.seller if seller == "seller" else "0x" + "0" * 40
    with pytest.raises(TransactionFailed):
        chain.contract.functions.pay(auction, target).transact({"from": chain.buyer, "value": value})


def test_contract_resists_a_seller_that_re_enters(chain):
    attacker_src = """
    pragma solidity ^0.8.24;
    interface IPay { function pay(uint256 id, address payable s) external payable; }
    contract Attacker {
        IPay target; uint256 id;
        constructor(address t) { target = IPay(t); }
        receive() external payable { target.pay{value: 1}(id, payable(address(this))); }
        function setId(uint256 i) external { id = i; }
    }"""
    out = solcx.compile_source(attacker_src, output_values=["abi", "bin"], solc_version="0.8.24")
    iface = next(v for k, v in out.items() if k.endswith(":Attacker"))
    w3 = chain.w3
    rc = w3.eth.wait_for_transaction_receipt(
        w3.eth.contract(abi=iface["abi"], bytecode=iface["bin"]).constructor(chain.contract.address).transact({"from": chain.deployer}))
    attacker = w3.eth.contract(address=rc.contractAddress, abi=iface["abi"])
    attacker.functions.setId(5).transact({"from": chain.deployer})
    with pytest.raises(TransactionFailed):  # the re-entrant call hits AlreadyPaid, so the whole payment reverts
        chain.contract.functions.pay(5, attacker.address).transact({"from": chain.buyer, "value": 100})
    assert chain.contract.functions.paid(5).call() is False and w3.eth.get_balance(chain.contract.address) == 0


# ---- development-only local chain + demo wallet ----------------------------------------------
@pytest.fixture
def local_app(tmp_path):
    class Local(TestConfig):
        LOCAL_CHAIN = True

    app = create_app(Local)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_local_chain_never_combines_with_a_real_rpc():
    class Both(TestConfig):
        LOCAL_CHAIN = True
        RPC_URL = "http://example.invalid"

    with pytest.raises(RuntimeError, match="development only"):
        create_app(Both)


def test_demo_wallet_does_not_exist_in_a_normal_deployment(app, users):
    c = client_for(app, "buyer@t.test")
    for path in ("/dev-wallet/", "/dev-wallet/account"):
        assert c.get(path).status_code == 404


def test_local_chain_end_to_end_through_the_demo_wallet(local_app):
    app = local_app
    cat = Category(name="Books")  # (not the shared `cats` fixture: that builds a different app and database)
    db.session.add(cat)
    db.session.commit()
    seller = make_user("seller@t.test", "seller")
    make_user("buyer@t.test")
    accounts = app.extensions["local_chain_accounts"]
    seller.link_wallet(accounts[2])
    db.session.commit()
    from app.services import auction_service as svc
    a = make_auction(seller, cat, "Demo", 100)
    buyer = User.query.filter_by(email="buyer@t.test").one()
    svc.place_bid(a.id, buyer, "32000")  # 32,000 INR = 0.1 ETH
    svc.close_auction(a.id, now=a.end_time + timedelta(seconds=1))
    c = client_for(app, "buyer@t.test")

    r = c.get("/dev-wallet/account")
    assert r.status_code == 200, (r.status_code, r.location)
    acct = r.json
    assert acct["address"] == accounts[1]
    prep = c.post(f"/payments/{a.id}/crypto/prepare", json={"wallet_address": acct["address"]}).json
    assert prep["quote"]["eth"] == "0.1"
    h = c.post("/dev-wallet/send", json={"tx": prep["tx"]}).json["hash"]
    assert h.startswith("0x") and len(h) == 66
    assert c.post(f"/payments/{a.id}/crypto/submit", json={"tx_hash": h}).json["ok"]
    assert c.get(f"/payments/{a.id}/status").json["status"] == "pending"  # 1 of 2 confirmations
    assert c.post("/dev-wallet/mine", json={"blocks": 1}).json["block"] > 0
    assert c.get(f"/payments/{a.id}/status").json["status"] == "successful"
    assert Payment.query.one().crypto.status == "confirmed"
    assert "Demo wallet" in c.get("/dev-wallet/").data.decode()


def test_demo_wallet_only_sends_from_itself_to_the_contract(local_app):
    app = local_app
    make_user("buyer@t.test")
    c = client_for(app, "buyer@t.test")
    accounts = app.extensions["local_chain_accounts"]
    contract = app.config["CONTRACT_ADDRESS"]
    for tx in ({"from": accounts[3], "to": contract, "value": "0x1", "data": "0x"},      # someone else's account
               {"from": accounts[1], "to": accounts[2], "value": "0x1", "data": "0x"},   # not the contract
               {}, {"from": accounts[1]}):
        r = c.post("/dev-wallet/send", json={"tx": tx})
        assert r.status_code == 400
    g.pop("_login_user", None)
    assert app.test_client().post("/dev-wallet/send", json={"tx": {}}).status_code == 302  # login required


# ---- the helper scripts ----------------------------------------------------------------------
def load_script(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, f"scripts/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_deploy_script_deploys_a_working_contract(chain, capsys):
    from eth_account import Account
    key = Account.create()
    chain.w3.eth.send_transaction({"from": chain.deployer, "to": key.address, "value": ETH})
    address, chain_id = load_script("deploy_contract").deploy(chain.w3, key.key.hex())
    assert chain_id == chain.w3.eth.chain_id and Web3.is_checksum_address(address)
    deployed = chain.w3.eth.contract(address=address, abi=ART["abi"])
    assert deployed.functions.paid(1).call() is False
    deployed.functions.pay(1, chain.seller).transact({"from": chain.buyer, "value": 5})
    assert deployed.functions.paid(1).call() is True
    out = capsys.readouterr().out
    assert key.address in out and key.key.hex().removeprefix("0x") not in out  # the key is never printed


def test_deploy_script_refuses_unfunded_deployers_and_mainnet(chain, monkeypatch):
    from eth_account import Account
    script = load_script("deploy_contract")
    with pytest.raises(SystemExit, match="no test ETH"):
        script.deploy(chain.w3, Account.create().key.hex())
    monkeypatch.setattr(type(chain.w3.eth), "chain_id", property(lambda self: 1))
    with pytest.raises(SystemExit, match="mainnet"):
        script.deploy(chain.w3, Account.create().key.hex())


def test_setup_checker_passes_for_a_good_setup_and_flags_bad_ones(app, chain, capsys):
    script = load_script("check_crypto_setup")
    assert script.check(app) == []
    out = capsys.readouterr().out
    assert "OK   connected to the node" in out and "answers paid(auctionId)" in out and "FAIL" not in out
    app.config["CONTRACT_ADDRESS"] = chain.other  # an ordinary account, not a contract
    assert any("no contract found" in p for p in script.check(app))
    app.config.update(CONTRACT_ADDRESS="not-an-address")
    assert any("not a valid address" in p for p in script.check(app))
    app.config.update(CONTRACT_ADDRESS=chain.contract.address, CHAIN_ID=1)  # setting disagrees with the node
    assert any("node chain id" in p and "CHAIN_ID setting 1" in p for p in script.check(app))
    app.config.update(CHAIN_ID=chain.w3.eth.chain_id, CONTRACT_ADDRESS=None)
    assert any("CONTRACT_ADDRESS is empty" in p for p in script.check(app))


def test_local_chain_advances_by_itself_while_a_payment_waits(local_app):
    app = local_app
    cat = Category(name="Books")
    db.session.add(cat)
    db.session.commit()
    seller, buyer = make_user("seller@t.test", "seller"), make_user("buyer@t.test")
    accounts = app.extensions["local_chain_accounts"]
    seller.link_wallet(accounts[2])
    db.session.commit()
    from app.services import auction_service as svc
    a = make_auction(seller, cat, "Demo", 100)
    svc.place_bid(a.id, buyer, "32000")
    svc.close_auction(a.id, now=a.end_time + timedelta(seconds=1))
    c = client_for(app, "buyer@t.test")
    prep = c.post(f"/payments/{a.id}/crypto/prepare", json={"wallet_address": accounts[1]}).json
    c.post(f"/payments/{a.id}/crypto/submit", json={"tx_hash": c.post("/dev-wallet/send", json={"tx": prep["tx"]}).json["hash"]})
    assert c.get(f"/payments/{a.id}/status").json["status"] == "pending"
    assert bc.verify_pending() == 1  # one background tick mines a block and confirms it
    assert c.get(f"/payments/{a.id}/status").json["status"] == "successful"
