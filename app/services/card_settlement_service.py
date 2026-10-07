"""Atomic settlement of a won card auction on CollectibleCardToken: payment and token transfer in one transaction.

1. The auction closes. The winner must have a wallet in their profile.
2. prepare_authorization(): the seller (the token's owner) signs authorizeSale(tokenId, auctionId, winner, price) in
   MetaMask. The server locks the quote in CryptoPayment so the on-chain price can be compared with it later.
3. authorization_state(): reads sales(tokenId) from the chain and compares it with the locked quote.
4. prepare_payment(): the winner signs settle(auctionId, tokenId) with the exact price as the value. The contract pays
   the seller and moves the token to the winner, or reverts and nothing happens.
5. blockchain_service.submit()/verify_payment() are reused; check_sale_event() verifies the CardSold event.

The server never holds a private key, and nothing the browser reports is trusted: the chain is read directly.
"""
import logging
from decimal import Decimal

from flask import current_app
from web3 import Web3
from web3.logs import DISCARD

from ..extensions import db
from ..models import CryptoPayment, utcnow
from . import blockchain_minting_service as bm
from . import blockchain_ownership_service as ownership
from .blockchain_service import Check, CryptoError, get_web3, normalize_wallet, quote

logger = logging.getLogger(__name__)
ZERO = "0x" + "00" * 20


def card_of(payment):
    return payment.auction.product.collectible_card


def applies(payment):
    """Payments for trading cards settle through the token contract; everything else uses AuctionPayment."""
    return card_of(payment) is not None


def _tokenised(payment):
    card = card_of(payment)
    asset = card.blockchain_asset
    if asset is None or asset.status != "minted" or asset.token_id is None:
        raise CryptoError("This card has no minted blockchain token, so it cannot be paid for in cryptocurrency.", 409)
    w3 = get_web3()
    if w3 is None or not bm.ARTIFACT.exists():
        raise CryptoError("Cryptocurrency payments are not available right now.", 503)
    if w3.eth.chain_id != int(current_app.config["CHAIN_ID"]):
        raise CryptoError("The blockchain node is on a different network than configured.", 503)
    return card, asset, w3


def _require_registered_owner(payment, asset):
    sync = ownership.check_ownership_sync(asset)
    if sync.status == ownership.SYNC_ERROR:
        raise CryptoError(f"OWNERSHIP SYNC ERROR: {sync.reason} The sale is on hold.", 409)
    if sync.status != ownership.IN_SYNC:
        raise CryptoError("Ownership of the token could not be verified on the blockchain right now.", 503)
    wallet = payment.auction.product.seller.wallet_address
    if not wallet or wallet.lower() != asset.owner_wallet.lower():
        raise CryptoError("The seller wallet no longer matches the registered owner of the token.", 409)


def _check_ready(payment):
    """Everything that must hold before the seller authorizes. Returns (asset, w3, seller_wallet, winner_wallet)."""
    auction = payment.auction
    if auction.status != "closed" or auction.winner is None or auction.winner.buyer_id != payment.buyer_id:
        raise CryptoError("This auction has no winner to sell to.", 409)
    if not payment.awaiting_payment:
        raise CryptoError("This payment is already paid or being processed.", 409)
    card, asset, w3 = _tokenised(payment)
    _require_registered_owner(payment, asset)
    winner_wallet = payment.buyer.wallet_address
    if not winner_wallet:
        raise CryptoError("The winning bidder has not added a wallet to their profile yet.", 409)
    seller_wallet = Web3.to_checksum_address(asset.owner_wallet)
    winner_wallet = Web3.to_checksum_address(winner_wallet)
    if winner_wallet == seller_wallet:
        raise CryptoError("The winner wallet and the seller wallet must be different.", 409)
    return asset, w3, seller_wallet, winner_wallet


def authorization_blockers(payment):
    """Why the seller cannot authorize right now, or None. No side effects."""
    try:
        _check_ready(payment)
    except CryptoError as e:
        return e.message
    return None


def _eth(amount):
    """0.250000000000000000 (as stored) -> 0.25, never in scientific notation."""
    return format(Decimal(amount).normalize(), "f")


def _chain():
    cfg = current_app.config
    return {"id": cfg["CHAIN_ID"], "id_hex": hex(cfg["CHAIN_ID"]), "name": cfg["CHAIN_NAME"]}


# ---- step 2: the seller authorizes ---------------------------------------------------------------
def prepare_authorization(payment, seller_wallet_raw):
    asset, w3, seller_wallet, winner_wallet = _check_ready(payment)
    try:
        connected = normalize_wallet(seller_wallet_raw)
    except ValueError as e:
        raise CryptoError(str(e))
    if connected is None:
        raise CryptoError("Connect your wallet first.")
    if connected != seller_wallet:
        raise CryptoError("Connect the wallet that owns the token: only the owner can authorize its sale.", 403)

    cfg = current_app.config
    wei, eth, rate = quote(payment.amount)
    row = payment.crypto or CryptoPayment(payment_id=payment.id)
    row.wallet_address, row.seller_address = winner_wallet, seller_wallet
    row.contract_address = Web3.to_checksum_address(asset.contract_address)
    row.cryptocurrency, row.expected_wei, row.amount, row.exchange_rate = "ETH", wei, eth, rate
    row.blockchain_network, row.chain_id = cfg["CHAIN_NAME"], cfg["CHAIN_ID"]
    row.transaction_hash = row.block_number = row.failure_reason = None
    row.confirmations, row.status, row.transaction_date = 0, "pending", utcnow()
    db.session.add(row)
    db.session.commit()

    data = bm._contract(w3, asset.contract_address).encode_abi(
        "authorizeSale", args=[asset.token_id, payment.auction_id, winner_wallet, wei])
    return {"tx": {"from": seller_wallet, "to": row.contract_address, "data": data, "value": "0x0"},
            "chain": _chain(),
            "terms": {"token_id": asset.token_id, "buyer": winner_wallet, "eth": _eth(eth), "wei": str(wei)}}


# ---- step 3: read the authorization back from the chain ------------------------------------------------
def authorization_state(payment):
    """{state: authorized | missing | mismatch | unavailable, reason} from sales(tokenId) on the chain."""
    row = payment.crypto
    if row is None or row.expected_wei is None:
        return {"state": "missing", "reason": "The seller has not authorized the transfer yet."}
    try:
        card, asset, w3 = _tokenised(payment)
        contract = bm._contract(w3, asset.contract_address)
        seller, buyer, price, auction_id = contract.functions.sales(asset.token_id).call()
        if seller == ZERO:
            return {"state": "missing", "reason": "The seller has not authorized the transfer yet."}
        terms_match = (seller.lower() == row.seller_address.lower() and buyer.lower() == row.wallet_address.lower()
                       and int(price) == int(row.expected_wei) and int(auction_id) == payment.auction_id
                       and contract.functions.ownerOf(asset.token_id).call().lower() == seller.lower())
        if not terms_match:
            return {"state": "mismatch", "reason": "The transfer the seller authorized does not match the winning bid."}
        return {"state": "authorized", "reason": None}
    except CryptoError as e:
        return {"state": "unavailable", "reason": e.message}
    except Exception:
        logger.warning("Could not read the sale terms for payment %s", payment.id, exc_info=True)
        return {"state": "unavailable", "reason": "The blockchain could not be read right now."}


# ---- step 4: the winner pays ---------------------------------------------------------------------
def prepare_payment(payment, buyer_wallet_raw):
    """The settle() transaction for the winner's wallet. Only possible once the seller's authorization is on-chain."""
    if not payment.awaiting_payment:
        raise CryptoError("This payment is already paid or being processed.", 409)
    try:
        buyer_wallet = normalize_wallet(buyer_wallet_raw)
    except ValueError as e:
        raise CryptoError(str(e))
    if buyer_wallet is None:
        raise CryptoError("Connect your wallet first.")
    card, asset, w3 = _tokenised(payment)

    state = authorization_state(payment)
    if state["state"] == "unavailable":
        raise CryptoError(state["reason"], 503)
    if state["state"] != "authorized":
        raise CryptoError(state["reason"], 409)
    row = payment.crypto
    if buyer_wallet.lower() != row.wallet_address.lower():
        raise CryptoError(f"The seller authorized this sale to the wallet {row.wallet_address[:6]}...{row.wallet_address[-4:]}. "
                          "Connect that wallet to pay.", 409)

    row.transaction_hash = row.block_number = row.failure_reason = None
    row.confirmations, row.status, row.transaction_date = 0, "pending", utcnow()
    db.session.commit()

    wei = int(row.expected_wei)
    data = bm._contract(w3, asset.contract_address).encode_abi("settle", args=[payment.auction_id, asset.token_id])
    return {"tx": {"from": buyer_wallet, "to": row.contract_address, "value": hex(wei), "data": data},
            "chain": _chain(),
            "quote": {"inr": f"{payment.amount:.2f}", "eth": _eth(row.amount), "wei": str(wei),
                      "rate": f"{row.exchange_rate:.2f}"},
            "seller_address": row.seller_address, "token_id": asset.token_id}


# ---- step 5: verify the settlement event ------------------------------------------------------------
def check_sale_event(w3, row, payment, receipt):
    """Returns (failure Check or None, paid wei). The transaction itself was already checked by the caller."""
    asset = card_of(payment).blockchain_asset
    address = row.contract_address.lower()
    contract = bm._contract(w3, row.contract_address)
    events = [e for e in contract.events.CardSold().process_receipt(receipt, errors=DISCARD)
              if e["address"].lower() == address and e["args"]["auctionId"] == payment.auction_id]
    if len(events) != 1:
        return Check("failed", "The transaction does not contain a settlement for this auction."), None
    args = events[0]["args"]
    if asset is None or args["tokenId"] != asset.token_id:
        return Check("failed", "The settlement moved a different card token."), None
    if args["seller"].lower() != row.seller_address.lower():
        return Check("failed", "The payment went to a different seller address."), None
    if args["buyer"].lower() != row.wallet_address.lower():
        return Check("failed", "The settlement was made by a different wallet."), None
    paid = int(args["amount"])
    if paid != int(row.expected_wei):
        return Check("failed", f"Wrong amount: expected {int(row.expected_wei) / 10**18:f} ETH, "
                               f"received {paid / 10**18:f} ETH.", amount_wei=paid), None
    return None, paid


# ---- what the pay page needs ------------------------------------------------------------------------------
def pay_context(payment):
    from .blockchain_service import explorer_url
    cfg = current_app.config
    try:
        card, asset, w3 = _tokenised(payment)
    except CryptoError as e:
        return {"enabled": False, "reason": e.message}
    row = payment.crypto
    if row is not None and row.expected_wei is not None:
        eth, rate = row.amount, row.exchange_rate
    else:
        _, eth, rate = quote(payment.amount)
    waiting = None
    if payment.awaiting_payment:
        state = authorization_state(payment)
        if state["state"] != "authorized":
            waiting = state["reason"]
    return {
        "enabled": True, "card": True, "token_id": asset.token_id, "waiting": waiting,
        "eth": _eth(eth), "rate": f"{rate:,.2f}", "seller_wallet": asset.owner_wallet,
        "buyer_wallet": row.wallet_address if row else None,
        "chain_name": cfg["CHAIN_NAME"], "chain_id_hex": hex(cfg["CHAIN_ID"]), "required": cfg["CONFIRMATIONS_REQUIRED"],
        "tx_hash": row.transaction_hash if row else None,
        "explorer": explorer_url(row.transaction_hash) if row else None,
        "confirmations": row.confirmations if row else 0, "dev_wallet": False,
    }
