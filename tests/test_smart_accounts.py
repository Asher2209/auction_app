"""Mints and card sales sent through a smart account (MetaMask EIP-7702): tx.to is the wrapper, not our contract.

Verification must rest on what our contract itself did (its events, with msg.sender in them), so a wrapped call is
accepted, while a wrapped call that reached another contract, or produced the wrong or forged events, is not.
"""
import pytest
from web3 import Web3

from app.extensions import db
from app.models import BlockchainTransfer, Payment
from app.services import blockchain_minting_service as bm
from app.services import card_settlement_service as css

from . import smart_account
from .test_card_settlement import (PRICE_WEI, as_buyer, authorize_on_chain, jpost, pay_url, prepare_payment,  # noqa: F401
                                   sold_card)
from .test_listing_validation import cat, card_type, seller  # noqa: F401 (fixtures)
from .test_minting import Chain, chain, verified_asset  # noqa: F401 (fixture)


# ---- minting through the admin's smart account ----------------------------------------------------------------------
@pytest.fixture
def admin_account(chain):
    """The platform admin's wallet as a smart account: it, not the key that signs, owns the token contract."""
    account = smart_account.deploy(chain.w3, chain.admin)
    chain.contract.functions.transferOwnership(account.address).transact({"from": chain.admin})
    return account


def wrapped_mint(asset, chain, account, target=None, data=None):
    prep = bm.initiate_mint(asset, account.address)
    tx_hash = smart_account.send_through(account, chain.admin, target or chain.address, data or prep["tx"]["data"])
    bm.submit_mint(asset, tx_hash)
    return bm.confirm_mint(asset)


def test_a_mint_sent_through_a_smart_account_is_accepted(seller, cat, card_type, chain, admin_account):
    asset = verified_asset(seller, cat, card_type, chain)
    result = wrapped_mint(asset, chain, admin_account)
    assert result["status"] == "confirmed" and asset.status == "minted" and asset.token_id == 1
    assert chain.contract.functions.ownerOf(1).call() == chain.seller_wallet


def test_a_wrapped_mint_on_another_contract_is_rejected(seller, cat, card_type, chain, admin_account):
    asset = verified_asset(seller, cat, card_type, chain)
    impostor = chain.w3.eth.contract(address=Chain.deploy(chain), abi=chain.contract.abi)
    impostor.functions.transferOwnership(admin_account.address).transact({"from": chain.admin})
    result = wrapped_mint(asset, chain, admin_account, target=impostor.address)  # a genuine CardMinted, wrong emitter
    assert result["status"] == "failed" and "not sent to the card token contract" in result["reason"]
    assert asset.status == "draft" and asset.token_id is None


def test_a_mint_event_forged_by_the_wrapper_is_rejected(seller, cat, card_type, chain, admin_account):
    asset = verified_asset(seller, cat, card_type, chain)
    bm.initiate_mint(asset, admin_account.address)
    forged = admin_account.functions.forgeMint(1, bm.platform_numeric_id(asset.collectible_card), chain.seller_wallet,
                                               bytes.fromhex(asset.metadata_hash[2:])).transact({"from": chain.admin})
    bm.submit_mint(asset, Web3.to_hex(forged))
    result = bm.confirm_mint(asset)
    assert result["status"] == "failed" and "not sent to the card token contract" in result["reason"]


def test_a_wrapped_mint_of_another_card_or_owner_is_rejected(seller, cat, card_type, chain, admin_account):
    mine, other = (verified_asset(seller, cat, card_type, chain) for _ in range(2))
    other_data = bm.initiate_mint(other, admin_account.address)["tx"]["data"]
    result = wrapped_mint(mine, chain, admin_account, data=other_data)
    assert result["status"] == "failed" and "different platform card" in result["reason"]

    bm.initiate_mint(mine, admin_account.address)
    to_stranger = chain.contract.encode_abi("mint", args=[chain.stranger, bm.platform_numeric_id(mine.collectible_card),
                                                          bytes.fromhex(mine.metadata_hash[2:])])
    result = wrapped_mint(mine, chain, admin_account, data=to_stranger)
    assert result["status"] == "failed" and "different wallet" in result["reason"]


# ---- the winner pays through a smart account -------------------------------------------------------------------------
@pytest.fixture
def wrapped_sale(client, users, cat, card_type, chain, seller):
    """A sold card whose winner's verified wallet is a smart account; the seller has authorized the sale to it."""
    s = sold_card(users, cat, card_type, chain)
    account = smart_account.deploy(chain.w3, chain.w3.eth.accounts[3])
    users["buyer"].link_wallet(account.address)
    db.session.commit()
    s.buyer_wallet = account.address
    authorize_on_chain(client, chain, s)
    as_buyer(client)
    return s, account


def submit_payment(client, s, tx_hash):
    assert jpost(client, pay_url(s, "/crypto/submit"), {"tx_hash": tx_hash}).get_json()["ok"]
    db.session.expire_all()
    return db.session.get(Payment, s.payment.id)


def test_a_settlement_sent_through_a_smart_account_is_accepted(client, chain, wrapped_sale):
    s, account = wrapped_sale
    prep = prepare_payment(client, s, wallet=account.address).get_json()
    assert prep["ok"], prep
    tx_hash = smart_account.send_through(account, chain.w3.eth.accounts[3], chain.address, prep["tx"]["data"],
                                         value=int(prep["tx"]["value"], 16))
    payment = submit_payment(client, s, tx_hash)
    assert payment.payment_status == "successful" and payment.crypto.status == "confirmed"
    assert chain.contract.functions.ownerOf(1).call() == account.address
    transfer = BlockchainTransfer.query.filter_by(transaction_hash=tx_hash).one()
    assert (transfer.from_wallet, transfer.to_wallet) == (chain.seller_wallet, account.address)


def test_a_settlement_forged_by_the_wrapper_is_rejected(client, chain, wrapped_sale):
    s, account = wrapped_sale
    prepare_payment(client, s, wallet=account.address)
    forged = account.functions.forgeSale(s.auction.id, 1, account.address, chain.seller_wallet, PRICE_WEI).transact(
        {"from": chain.w3.eth.accounts[3], "value": PRICE_WEI})
    payment = submit_payment(client, s, Web3.to_hex(forged))
    assert payment.payment_status == "failed" and "not sent to the payment contract" in payment.failure_reason
    assert chain.contract.functions.ownerOf(1).call() == chain.seller_wallet


def test_a_settlement_without_the_token_transfer_event_is_rejected(client, chain, wrapped_sale):
    """CardSold alone is not enough: the token contract's own Transfer of this token, seller to buyer, must be there."""
    s, account = wrapped_sale
    prep = prepare_payment(client, s, wallet=account.address).get_json()
    tx_hash = smart_account.send_through(account, chain.w3.eth.accounts[3], chain.address, prep["tx"]["data"],
                                         value=int(prep["tx"]["value"], 16))
    receipt = chain.w3.eth.get_transaction_receipt(tx_hash)
    transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)")
    without = dict(receipt, logs=[log for log in receipt["logs"] if log["topics"][0] != transfer_topic])
    payment = db.session.get(Payment, s.payment.id)
    failure, _ = css.check_sale_event(chain.w3, payment.crypto, payment, without)
    assert failure is not None and "did not transfer the card token" in failure.reason
    assert css.check_sale_event(chain.w3, payment.crypto, payment, receipt) == (None, PRICE_WEI)
