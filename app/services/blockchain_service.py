"""Cryptocurrency payments on an Ethereum TEST network (Sepolia by default).

Flow
----
1. prepare(): the buyer connects a wallet. The server locks a quote (INR -> wei at the configured rate),
   remembers the buyer's and seller's wallet addresses, and builds the exact transaction for the
   AuctionPayment contract: `pay(auctionId, seller)` with the quoted value.
2. The browser asks MetaMask to sign and send that transaction. The server never sees a key.
3. submit(): the browser reports the transaction hash. It is stored (unique) and the payment becomes "processing".
4. verify_payment(): the server reads the chain itself and checks, in order: the transaction exists and is
   mined, it did not revert, it targets our contract on the right network, it came from the connected
   wallet, and its PaymentMade event names this auction, this seller and this buyer with at least the
   quoted amount. Then it waits for the required confirmations. Only then is the payment marked successful.

Nothing the browser says is trusted: the chain is the source of truth. Private keys and seed phrases are
never requested, stored or logged.
"""
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path

from flask import current_app
from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from web3 import Web3
from web3.exceptions import TransactionNotFound

from ..extensions import db
from ..models import CryptoPayment, Payment, utcnow
from . import payment_service
from .notifications import notify

ARTIFACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "build" / "AuctionPayment.json"
TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PRIVATE_KEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
ZERO_ADDRESS = "0x" + "0" * 40


class CryptoError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Check:
    status: str  # pending / failed / confirmed
    reason: str | None = None
    confirmations: int = 0
    block_number: int | None = None
    amount_wei: int | None = None


# ---- configuration / chain access ---------------------------------------------------------
def _abi():
    return json.loads(ARTIFACT.read_text())["abi"]


def get_web3():
    """The Web3 connection: an injected/local chain, else the configured RPC node, else None."""
    ext = current_app.extensions
    if "web3" in ext:
        return ext["web3"]
    url = current_app.config.get("RPC_URL")
    if not url:
        return None
    ext["web3"] = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
    return ext["web3"]


def crypto_enabled():
    cfg = current_app.config
    return bool(get_web3() and cfg.get("CONTRACT_ADDRESS") and ARTIFACT.exists())


def _contract(w3):
    return w3.eth.contract(address=Web3.to_checksum_address(current_app.config["CONTRACT_ADDRESS"]), abi=_abi())


def explorer_url(tx_hash):
    base = current_app.config.get("BLOCK_EXPLORER_TX_URL")
    return f"{base}{tx_hash}" if base and tx_hash else None


# ---- wallet addresses ---------------------------------------------------------------------
def normalize_wallet(raw):
    """Return the EIP-55 checksummed address, None for blank, or raise ValueError with a friendly message.

    Rejects anything that looks like a private key or seed phrase, so people cannot paste secrets by mistake.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):  # JSON can carry numbers/lists/objects: never call string methods on those
        raise ValueError("Enter a valid address: 0x followed by 40 hexadecimal characters.")
    text = raw.strip()
    if not text:
        return None
    if PRIVATE_KEY_RE.match(text) or len(text.split()) > 1:
        raise ValueError("That is not a public address. Never enter a private key or seed phrase anywhere.")
    if not ADDRESS_RE.match(text):
        raise ValueError("Enter a valid address: 0x followed by 40 hexadecimal characters.")
    body = text[2:]
    if body not in (body.lower(), body.upper()) and not Web3.is_checksum_address(text):
        raise ValueError("The address checksum is wrong: check for a typo.")
    if int(body, 16) == 0:
        raise ValueError("The zero address cannot be used.")
    return Web3.to_checksum_address(text)


# ---- quoting ------------------------------------------------------------------------------
def quote(inr_amount):
    """Return (wei, eth_decimal, rate) for an INR amount, rounding the wei UP so the seller is never short."""
    rate = Decimal(current_app.config["INR_PER_ETH"])
    with localcontext() as ctx:
        ctx.prec = 60
        wei = int((Decimal(inr_amount) * Decimal(10) ** 18 / rate).to_integral_value(rounding=ROUND_CEILING))
        eth = Decimal(wei) / Decimal(10) ** 18
    return wei, eth, rate


# ---- step 1: prepare -----------------------------------------------------------------------
def prepare(payment, buyer_wallet_raw):
    """Lock a quote and build the transaction for the buyer's wallet to sign."""
    if not crypto_enabled():
        raise CryptoError("Cryptocurrency payments are not available right now.", 503)
    if not payment.awaiting_payment:
        raise CryptoError("This payment is already paid or being processed.", 409)
    try:
        buyer_wallet = normalize_wallet(buyer_wallet_raw)
    except ValueError as e:
        raise CryptoError(str(e))
    if buyer_wallet is None:
        raise CryptoError("Connect your wallet first.")
    seller = payment.auction.product.seller
    if not seller.wallet_address:
        raise CryptoError("The seller has not added a payout wallet yet, so this cannot be paid in crypto.", 409)
    if buyer_wallet.lower() == seller.wallet_address.lower():
        raise CryptoError("Your wallet and the seller's wallet must be different.")

    cfg = current_app.config
    wei, eth, rate = quote(payment.amount)
    contract = _contract(get_web3())
    row = payment.crypto or CryptoPayment(payment_id=payment.id)
    row.wallet_address, row.seller_address = buyer_wallet, seller.wallet_address
    row.contract_address = Web3.to_checksum_address(cfg["CONTRACT_ADDRESS"])
    row.cryptocurrency, row.expected_wei, row.amount, row.exchange_rate = "ETH", wei, eth, rate
    row.blockchain_network, row.chain_id = cfg["CHAIN_NAME"], cfg["CHAIN_ID"]
    row.transaction_hash = row.block_number = row.failure_reason = None
    row.confirmations, row.status, row.transaction_date = 0, "pending", utcnow()
    db.session.add(row)
    db.session.commit()

    data = contract.encode_abi("pay", args=[payment.auction_id, seller.wallet_address])
    return {
        "tx": {"from": buyer_wallet, "to": row.contract_address, "value": hex(wei), "data": data},
        "chain": {"id": cfg["CHAIN_ID"], "id_hex": hex(cfg["CHAIN_ID"]), "name": cfg["CHAIN_NAME"]},
        "quote": {"inr": f"{payment.amount:.2f}", "eth": format(eth, "f"), "wei": str(wei), "rate": f"{rate:.2f}"},
        "seller_address": seller.wallet_address,
    }


# ---- step 3: submit the transaction hash ---------------------------------------------------
def submit(payment, tx_hash_raw, now=None):
    now = now or utcnow()
    tx_hash = tx_hash_raw.strip() if isinstance(tx_hash_raw, str) else ""
    if not TX_HASH_RE.match(tx_hash):
        raise CryptoError("That is not a valid transaction hash.")
    tx_hash = tx_hash.lower()
    row = payment.crypto
    if row is None or row.transaction_hash is not None or row.status != "pending":
        raise CryptoError("Start the crypto payment first, then approve it in your wallet.", 409)
    if CryptoPayment.query.filter_by(transaction_hash=tx_hash).first():
        raise CryptoError("That transaction has already been used for a payment.", 409)

    claimed = db.session.execute(
        update(Payment).where(
            Payment.id == payment.id, Payment.buyer_id == payment.buyer_id,
            or_(Payment.payment_status == "failed",
                and_(Payment.payment_status == "pending", Payment.payment_method.is_(None)))
        ).values(payment_method="crypto", method_detail="eth", payment_status="pending", failure_reason=None,
                 reference=f"ETH {row.wallet_address[:6]}...{row.wallet_address[-4:]}", settle_at=None,
                 attempts=Payment.attempts + 1),
        execution_options={"synchronize_session": False}).rowcount
    if claimed != 1:
        db.session.rollback()
        raise CryptoError("This payment is already paid or being processed.", 409)
    row.transaction_hash, row.transaction_date, row.status = tx_hash, now, "pending"
    try:
        db.session.commit()
    except IntegrityError:  # the same hash raced in from another payment
        db.session.rollback()
        raise CryptoError("That transaction has already been used for a payment.", 409)
    db.session.expire_all()
    return db.session.get(Payment, payment.id)


# ---- step 4: verify on chain --------------------------------------------------------------
def check_transaction(w3, row, payment, now):
    """Read the chain and decide. Pure with respect to the database: returns a Check."""
    cfg = current_app.config
    required = cfg["CONFIRMATIONS_REQUIRED"]
    if w3.eth.chain_id != row.chain_id:
        # The configured node is on a different network from the one this payment was quoted for.
        raise CryptoError("The blockchain node is on a different network than configured.", 503)

    try:
        tx = w3.eth.get_transaction(row.transaction_hash)
    except TransactionNotFound:
        timeout = timedelta(minutes=cfg["CRYPTO_NOT_FOUND_TIMEOUT_MINUTES"])
        if row.transaction_date and now - row.transaction_date > timeout:
            return Check("failed", "The transaction was never found on the network.")
        return Check("pending", "Waiting for the network to see the transaction.")

    tx_chain = tx.get("chainId")
    if tx_chain is not None and int(tx_chain) != row.chain_id:
        return Check("failed", "The transaction was sent on the wrong network.")

    try:
        receipt = w3.eth.get_transaction_receipt(row.transaction_hash)
    except TransactionNotFound:
        return Check("pending", "Waiting for the transaction to be included in a block.")

    if receipt["status"] != 1:
        return Check("failed", "The transaction failed on the blockchain.")
    contract_addr = row.contract_address.lower()
    if (tx.get("to") or "").lower() != contract_addr or (receipt.get("to") or "").lower() != contract_addr:
        return Check("failed", "The transaction was not sent to the payment contract.")
    if tx["from"].lower() != row.wallet_address.lower():
        return Check("failed", "The transaction came from a different wallet than the one connected.")

    events = [e for e in _contract(w3).events.PaymentMade().process_receipt(receipt)
              if e["address"].lower() == contract_addr and e["args"]["auctionId"] == payment.auction_id]
    if len(events) != 1:
        return Check("failed", "The transaction does not contain a payment for this auction.")
    args = events[0]["args"]
    if args["seller"].lower() != row.seller_address.lower():
        return Check("failed", "The payment went to a different seller address.")
    if args["buyer"].lower() != row.wallet_address.lower():
        return Check("failed", "The payment was made by a different wallet.")
    paid = int(args["amount"])
    if paid < int(row.expected_wei):
        return Check("failed", f"Underpaid: expected {Decimal(row.expected_wei) / 10**18:f} ETH, "
                               f"received {Decimal(paid) / 10**18:f} ETH.", amount_wei=paid)

    confirmations = max(0, w3.eth.block_number - receipt["blockNumber"] + 1)
    if confirmations < required:
        return Check("pending", f"Waiting for confirmations ({confirmations}/{required}).",
                     confirmations, receipt["blockNumber"], paid)
    return Check("confirmed", None, confirmations, receipt["blockNumber"], paid)


def verify_payment(payment, now=None):
    """Verify a submitted crypto payment against the chain and apply the outcome. Returns the CryptoPayment."""
    now = now or utcnow()
    row = payment.crypto
    if (row is None or row.status != "pending" or not row.transaction_hash
            or payment.payment_method != "crypto" or payment.payment_status != "pending"):
        return row
    w3 = get_web3()
    if w3 is None:
        return row
    result = check_transaction(w3, row, payment, now)

    if result.status == "pending":
        row.confirmations, row.block_number = result.confirmations, result.block_number
        db.session.commit()
        return row

    new_status = "successful" if result.status == "confirmed" else "failed"
    values = {"payment_status": new_status}
    if new_status == "successful":
        values.update(payment_date=now, failure_reason=None)
    else:
        values.update(failure_reason=result.reason)
    claimed = db.session.execute(  # only the first verifier to see the outcome applies it
        update(Payment).where(Payment.id == payment.id, Payment.payment_status == "pending",
                              Payment.payment_method == "crypto").values(**values),
        execution_options={"synchronize_session": False}).rowcount
    if claimed != 1:
        db.session.rollback()
        return row

    db.session.expire_all()
    payment = db.session.get(Payment, payment.id)
    row = payment.crypto
    row.confirmations, row.block_number = result.confirmations, result.block_number
    if new_status == "successful":
        row.status = "confirmed"
        row.amount = Decimal(result.amount_wei) / Decimal(10) ** 18
        row.failure_reason = None
        payment_service.on_success(payment, now)
    else:
        row.status, row.failure_reason = "failed", result.reason
        notify(payment.buyer_id, "Payment failed",
               f'Your crypto payment for "{payment.auction.product.title}" could not be confirmed: {result.reason}',
               url=f"/payments/{payment.auction_id}")
    db.session.commit()
    return row


def recheck(payment, now=None):
    """Read-only on-chain re-check of an already confirmed payment (used by the public invoice page).

    Returns a Check, or None when the chain cannot be reached. Never writes to the database.
    """
    row = payment.crypto
    if not crypto_enabled() or row is None or not row.transaction_hash:
        return None
    try:
        return check_transaction(get_web3(), row, payment, now or utcnow())
    except Exception:  # node down, wrong network configured, ...
        current_app.logger.warning("On-chain re-check failed for payment %s", payment.id, exc_info=True)
        return None


def verify_pending(now=None):
    """Scheduler/background check of every submitted-but-unresolved crypto payment. Never raises."""
    if not crypto_enabled():
        return 0
    now = now or utcnow()
    checked = 0
    pending = Payment.query.filter_by(payment_method="crypto", payment_status="pending").all()
    if pending and current_app.extensions.get("local_chain_accounts"):
        # Development chain only: nothing mines blocks on its own, so let time pass here
        # (a real network does this by itself) and confirmations accrue while payments wait.
        get_web3().provider.ethereum_tester.mine_blocks(1)
    for payment in pending:
        if payment.crypto and payment.crypto.transaction_hash:
            try:
                verify_payment(payment, now)
                checked += 1
            except Exception:  # an RPC outage must not stop the other payments or the scheduler
                db.session.rollback()
                current_app.logger.warning("Crypto verification failed for payment %s", payment.id, exc_info=True)
    return checked


# ---- development-only in-process chain ---------------------------------------------------
def init_local_chain(app):
    """Start an in-memory test chain and deploy the contract (LOCAL_CHAIN=1). Never used with a real RPC."""
    if app.config.get("RPC_URL"):
        raise RuntimeError("LOCAL_CHAIN cannot be combined with RPC_URL: the local chain is for development only.")
    from web3 import EthereumTesterProvider
    w3 = Web3(EthereumTesterProvider())
    deployer = w3.eth.accounts[0]
    art = json.loads(ARTIFACT.read_text())
    receipt = w3.eth.wait_for_transaction_receipt(
        w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]).constructor().transact({"from": deployer}))
    app.extensions["web3"] = w3
    app.config.update(CONTRACT_ADDRESS=receipt.contractAddress, CHAIN_ID=w3.eth.chain_id,
                      CHAIN_NAME="Local test chain", BLOCK_EXPLORER_TX_URL=None, CONFIRMATIONS_REQUIRED=2)
    app.extensions["local_chain_accounts"] = list(w3.eth.accounts)
    return w3
