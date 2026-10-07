"""Mint one CollectibleCardToken per platform-verified card, signed by the admin wallet in MetaMask.

Flow
----
1. initiate_mint(): checks the card is verified and the connected wallet owns the token contract, then
   builds the exact mint transaction for the browser wallet to sign. The server holds no private key.
2. submit_mint(): the browser reports the transaction hash; the asset becomes "minting".
3. confirm_mint(): the server reads the chain itself. Only a transaction that succeeded, targets our token
   contract on the right network, emitted our CardMinted event for THIS card and owner with the recorded
   verification hash, and has enough confirmations completes the mint. The token ID is read from that event.
"""
import json
import logging
import re
from pathlib import Path

from flask import current_app
from sqlalchemy.exc import IntegrityError
from web3 import Web3
from web3.exceptions import TransactionNotFound
from web3.logs import DISCARD

from ..extensions import db
from ..models import utcnow
from .blockchain_service import TX_HASH_RE, get_web3, normalize_wallet

logger = logging.getLogger(__name__)
ARTIFACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "build" / "CollectibleCardToken.json"
IDENTITY_FIELDS = ("card_name", "set_name", "set_code", "release_year", "card_number", "edition", "language",
                   "manufacturer", "grading_company", "grade", "certification_number")


class MintError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _contract(w3, address):
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=json.loads(ARTIFACT.read_text())["abi"])


def platform_numeric_id(card):
    """CARD-000123 -> 123. The contract refuses 0, so a malformed or zero ID is rejected here too."""
    match = re.fullmatch(r"CARD-(\d+)", card.platform_card_id or "")
    if not match or int(match.group(1)) == 0:
        raise MintError("The card does not have a valid platform ID.")
    return int(match.group(1))


def verification_hash(card):
    """keccak256 of the card's identity fields (canonical JSON): the fingerprint recorded on-chain at mint."""
    record = {"platform_card_id": card.platform_card_id, **{f: getattr(card, f) for f in IDENTITY_FIELDS}}
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return Web3.to_hex(Web3.keccak(text=canonical))


def chain_info():
    cfg = current_app.config
    return {"id_hex": hex(int(cfg["CHAIN_ID"])), "name": cfg["CHAIN_NAME"]}


def chain_ready():
    return get_web3() is not None and ARTIFACT.exists()


def _require_chain():
    w3 = get_web3()
    if w3 is None or not ARTIFACT.exists():
        raise MintError("Blockchain is not configured.", 503)
    return w3


# ---- step 1: prepare -----------------------------------------------------------------------
def initiate_mint(asset, minter_wallet_raw):
    card = asset.collectible_card
    verification = card.product.collectible_verification
    if verification is None or verification.verification_status != "verified":
        raise MintError("Only platform-verified cards can be minted.")
    if asset.status != "draft":
        raise MintError(f"The asset must be a draft to mint, not {asset.status}.", 409)
    platform_id = platform_numeric_id(card)
    w3 = _require_chain()
    try:
        minter = normalize_wallet(minter_wallet_raw)
    except ValueError as e:
        raise MintError(str(e))
    if minter is None:
        raise MintError("Connect your wallet first.")

    contract = _contract(w3, asset.contract_address)
    try:
        contract_owner = contract.functions.owner().call()
        existing = contract.functions.tokenIdOfPlatformId(platform_id).call()
    except Exception:
        raise MintError("Could not read the token contract. Check COLLECTIBLE_CONTRACT_ADDRESS and the network.", 503)
    if contract_owner.lower() != minter.lower():
        raise MintError("Only the token contract owner's wallet can mint. Connect the platform admin wallet.", 403)
    if existing != 0:
        raise MintError("This card is already registered on the blockchain.", 409)

    digest = verification_hash(card)
    asset.metadata_hash = digest
    db.session.commit()
    data = contract.encode_abi("mint", args=[Web3.to_checksum_address(asset.owner_wallet), platform_id,
                                             bytes.fromhex(digest[2:])])
    return {"tx": {"from": minter, "to": Web3.to_checksum_address(asset.contract_address), "data": data, "value": "0x0"},
            "chain": chain_info(), "verification_hash": digest}


# ---- step 2: submit --------------------------------------------------------------------------
def submit_mint(asset, tx_hash_raw):
    tx_hash = tx_hash_raw.strip().lower() if isinstance(tx_hash_raw, str) else ""
    if not TX_HASH_RE.match(tx_hash):
        raise MintError("That is not a valid transaction hash.")
    if asset.status not in ("draft", "minting"):
        raise MintError(f"A {asset.status} asset cannot be minted.", 409)
    asset.status = "minting"
    asset.mint_transaction_hash = tx_hash
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise MintError("That transaction hash is already attached to another asset.", 409)
    return asset


# ---- step 3: verify on-chain, then complete ----------------------------------------------------
def _failed(reason):
    return {"status": "failed", "reason": reason}


def verify_mint(asset):
    """Read the chain and return {status: pending|failed|error|confirmed, ...}. Never changes the database."""
    if not asset.mint_transaction_hash:
        return {"status": "pending", "reason": "No transaction has been submitted yet."}
    w3 = get_web3()
    if w3 is None or not ARTIFACT.exists():
        return {"status": "error", "reason": "Blockchain is not configured."}
    try:
        if w3.eth.chain_id != int(current_app.config["CHAIN_ID"]):
            return {"status": "error", "reason": "The configured RPC node is on a different network than CHAIN_ID."}
        try:
            receipt = w3.eth.get_transaction_receipt(asset.mint_transaction_hash)
            tx = w3.eth.get_transaction(asset.mint_transaction_hash)
        except TransactionNotFound:
            return {"status": "pending", "reason": "The transaction has not been mined yet."}

        if receipt["status"] != 1:
            return _failed("The transaction reverted on the blockchain.")
        address = asset.contract_address.lower()
        if (tx["to"] or "").lower() != address:
            return _failed("The transaction was not sent to the card token contract.")

        contract = _contract(w3, asset.contract_address)
        events = [e for e in contract.events.CardMinted().process_receipt(receipt, errors=DISCARD)
                  if e["address"].lower() == address]
        if len(events) != 1:
            return _failed("The transaction did not emit exactly one CardMinted event from the token contract.")
        args = events[0]["args"]

        platform_id = platform_numeric_id(asset.collectible_card)
        if args["platformId"] != platform_id:
            return _failed("The minted token belongs to a different platform card ID.")
        if args["owner"].lower() != asset.owner_wallet.lower():
            return _failed("The token was minted to a different wallet than the recorded owner.")
        if Web3.to_hex(args["verificationHash"]).lower() != (asset.metadata_hash or "").lower():
            return _failed("The on-chain verification hash does not match the card record.")
        if contract.functions.tokenIdOfPlatformId(platform_id).call() != args["tokenId"]:
            return _failed("The contract's registry disagrees with the mint event.")

        confirmations = w3.eth.block_number - receipt["blockNumber"] + 1
        required = int(current_app.config["CONFIRMATIONS_REQUIRED"])
        if confirmations < required:
            return {"status": "pending", "reason": f"Waiting for confirmations ({confirmations}/{required}).",
                    "confirmations": confirmations}
        return {"status": "confirmed", "token_id": int(args["tokenId"]), "block_number": receipt["blockNumber"],
                "confirmations": confirmations}
    except Exception as exc:  # RPC outage etc.: say nothing about the transaction itself
        logger.warning("Mint verification could not complete for asset %s: %s", asset.id, exc)
        return {"status": "error", "reason": "The blockchain could not be read. Try again shortly."}


def confirm_mint(asset):
    """Verify the submitted mint and, only if it is genuine and confirmed, record the real token ID."""
    if asset.status == "minted":
        return {"status": "confirmed", "token_id": asset.token_id, "block_number": asset.mint_block_number}
    result = verify_mint(asset)
    if result["status"] == "confirmed":
        asset.token_id = result["token_id"]
        asset.mint_block_number = result["block_number"]
        asset.mint_date = utcnow()
        asset.status = "minted"
        from .qrcode_service import card_public_url  # the token points at the public card page
        asset.token_uri = card_public_url(asset.collectible_card.platform_card_id)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {"status": "error", "reason": "That token ID is already recorded for another asset."}
    elif result["status"] == "failed" and asset.status == "minting":
        logger.warning("Mint of asset %s failed verification: %s", asset.id, result["reason"])
        asset.status = "draft"
        asset.mint_transaction_hash = None
        db.session.commit()
    return result
