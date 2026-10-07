"""Linking a wallet to an account means proving control of it.

The server issues a one-time message naming the wallet, the account, this site and a random nonce. The user signs it
in their wallet (personal_sign) and the server recovers the signer from the signature. Only a match links the wallet.
Signing a message sends no transaction and costs no gas, and nothing secret is ever sent to or stored by the server.

Every payment and every card token is directed to User.verified_wallet, never to an address someone merely typed.
"""
import re
import secrets
import time
from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_defunct
from flask import current_app, session
from sqlalchemy import func

from ..extensions import db
from ..models import CollectibleCard, Product, User
from .blockchain_service import normalize_wallet
from .card_identity_service import create_blockchain_asset

CHALLENGE_KEY = "wallet_challenge"
CHALLENGE_TTL = 300  # seconds a message stays valid
SIGNATURE_RE = re.compile(r"^0x[0-9a-fA-F]{130}$")


class WalletError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _address(raw):
    try:
        address = normalize_wallet(raw)
    except ValueError as e:
        raise WalletError(str(e))
    if address is None:
        raise WalletError("Connect your wallet first.")
    return address


def _other_holder(user, address):
    return User.query.filter(func.lower(User.wallet_address) == address.lower(), User.id != user.id).first()


def challenge_message(user, address, host, nonce, issued):
    when = datetime.fromtimestamp(issued, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return (
        "ChainBid: confirm that you control this wallet\n"
        "\n"
        f"Wallet: {address}\n"
        f"Account: #{user.id}\n"
        f"Site: {host}\n"
        f"Nonce: {nonce}\n"
        f"Issued: {when} UTC\n"
        "\n"
        "Signing proves you hold this wallet. It does not send a transaction, cost gas or give anyone access to your funds."
    )


def start(user, raw_address, host, now=None):
    """Step 1: a fresh message for this user and wallet, valid for CHALLENGE_TTL seconds and usable once."""
    address = _address(raw_address)
    holder = _other_holder(user, address)
    if holder is not None and holder.has_verified_wallet:
        raise WalletError("This wallet is already linked to another account.", 409)
    issued = int(now if now is not None else time.time())
    message = challenge_message(user, address, host, secrets.token_hex(16), issued)
    session[CHALLENGE_KEY] = {"user": user.id, "address": address, "message": message, "issued": issued}
    return message


def finish(user, raw_address, signature, now=None):
    """Step 2: link the wallet if the signature over the issued message was made by it."""
    pending = session.pop(CHALLENGE_KEY, None)  # one attempt per message, whatever the outcome
    if not isinstance(pending, dict) or pending.get("user") != user.id:
        raise WalletError("Ask for a new message to sign, then try again.")
    if (now if now is not None else time.time()) - pending["issued"] > CHALLENGE_TTL:
        raise WalletError("That message has expired. Ask for a new one.")
    address = _address(raw_address)
    if address != pending["address"]:
        raise WalletError("This is not the wallet the message was made for.")
    if not isinstance(signature, str) or not SIGNATURE_RE.match(signature):
        raise WalletError("That is not a valid signature.")
    try:
        signer = Account.recover_message(encode_defunct(text=pending["message"]), signature=signature)
    except Exception:
        raise WalletError("The signature could not be checked.")
    if signer.lower() != address.lower():
        raise WalletError("The signature was not made by this wallet.", 403)

    holder = _other_holder(user, address)
    if holder is not None:
        if holder.has_verified_wallet:
            raise WalletError("This wallet is already linked to another account.", 409)
        holder.unlink_wallet()  # an unproven claim on the address gives way to its proven owner
        db.session.flush()
    user.link_wallet(address)
    db.session.commit()
    result = follow_wallet(user)
    db.session.commit()
    return {"address": address, **result}


def unlink(user):
    user.unlink_wallet()
    db.session.commit()


def follow_wallet(user):
    """After a seller proves a wallet: give their verified cards that have no blockchain identity one, owned by it,
    and point identities that are not minted yet at it. A minted token belongs to whoever holds it on the chain."""
    if user.role != "seller" or not user.has_verified_wallet:
        return {"registered": 0, "moved": 0}
    contract = current_app.config.get("COLLECTIBLE_CONTRACT_ADDRESS")
    registered = moved = 0
    cards = CollectibleCard.query.join(Product, CollectibleCard.product_id == Product.id).filter(Product.seller_id == user.id)
    for card in cards:
        verification = card.product.collectible_verification
        if verification is None or verification.verification_status != "verified":
            continue
        asset = card.blockchain_asset
        if asset is None:
            if contract:
                create_blockchain_asset(card, user.wallet_address, contract, current_app.config["CHAIN_NAME"].lower())
                registered += 1
        elif asset.status == "draft" and (asset.owner_wallet or "").lower() != user.wallet_address.lower():
            asset.owner_wallet = user.wallet_address
            moved += 1
    return {"registered": registered, "moved": moved}
