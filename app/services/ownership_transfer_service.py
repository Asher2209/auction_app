"""Keep MySQL's record of who owns a card token in step with the blockchain, and keep the history.

The chain is the ledger of record. MySQL is updated only from facts read from the chain:
* record_settlement(): a verified CardSold settlement moves the owner, in the same transaction as the payment.
* reconcile_ownership(): an admin explicitly adopts the on-chain owner when the two disagree. The transfer is
  recorded from the chain's own Transfer event, with its real transaction hash. Nothing is ever overwritten silently:
  until then the mismatch is reported as an OWNERSHIP SYNC ERROR and the card cannot be listed.
"""
import logging

from web3 import Web3
from web3.exceptions import ContractLogicError

from ..extensions import db
from ..models import BlockchainTransfer, utcnow
from . import blockchain_minting_service as bm
from .blockchain_service import get_web3
from .notifications import notify

logger = logging.getLogger(__name__)


class ReconcileError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def history(asset):
    """Confirmed ownership transfers of a token, oldest first."""
    return (BlockchainTransfer.query.filter_by(blockchain_asset_id=asset.id, status="confirmed")
            .order_by(BlockchainTransfer.confirmed_at.asc(), BlockchainTransfer.id.asc()).all())


def transfer_for_payment(payment):
    return BlockchainTransfer.query.filter_by(auction_id=payment.auction_id, status="confirmed").first()


def record_settlement(payment, row, now=None):
    """Apply a verified settlement to MySQL: new owner, a transfer record, the card marked transferred.

    Runs inside the caller's transaction and is idempotent, so a repeated verification changes nothing.
    """
    now = now or utcnow()
    asset = payment.auction.product.collectible_card.blockchain_asset
    if asset is None or not row.transaction_hash:
        return None
    seller, buyer = row.seller_address, row.wallet_address

    announce = False
    transfer = BlockchainTransfer.query.filter_by(transaction_hash=row.transaction_hash).first()
    if transfer is None:
        announce = True
        transfer = BlockchainTransfer(
            blockchain_asset_id=asset.id, from_wallet=seller, to_wallet=buyer, auction_id=payment.auction_id,
            transaction_hash=row.transaction_hash, block_number=row.block_number, chain_id=row.chain_id,
            network=asset.blockchain_network, status="confirmed", requested_at=row.transaction_date or now,
            confirmed_at=now)
        db.session.add(transfer)
    elif transfer.auction_id is None:  # an admin reconciliation got there first: attach the sale to it
        transfer.auction_id = payment.auction_id
        announce = True

    if asset.owner_wallet.lower() != buyer.lower():
        asset.previous_owner = asset.owner_wallet
        asset.owner_wallet = buyer
    asset.status = "transferred"
    if announce:
        notify(payment.buyer_id, "You now own the card token",
               f'Token #{asset.token_id} for "{payment.auction.product.title}" is now owned by your wallet.',
               url=f"/payments/{payment.auction_id}")
    return transfer


def reconcile_ownership(asset):
    """Adopt the on-chain owner as the recorded owner. Returns {changed, owner}. Raises ReconcileError."""
    if asset.token_id is None or asset.status not in ("minted", "transferred"):
        raise ReconcileError("Only a minted token can be reconciled.", 409)
    w3 = get_web3()
    if w3 is None or not bm.ARTIFACT.exists():
        raise ReconcileError("Blockchain is not configured.", 503)
    contract = bm._contract(w3, asset.contract_address)
    try:
        chain_owner = Web3.to_checksum_address(contract.functions.ownerOf(asset.token_id).call())
    except ContractLogicError:
        raise ReconcileError("The token does not exist on the blockchain, so there is nothing to adopt.", 409)
    except Exception:
        raise ReconcileError("The blockchain could not be read right now.", 503)
    if chain_owner.lower() == asset.owner_wallet.lower():
        return {"changed": False, "owner": chain_owner}

    try:
        logs = contract.events.Transfer().get_logs(from_block=asset.mint_block_number or 0,
                                                   argument_filters={"tokenId": asset.token_id})
    except Exception:
        raise ReconcileError("The transfer history could not be read from the blockchain right now.", 503)
    arrivals = [log for log in logs if log["args"]["to"].lower() == chain_owner.lower()]
    if not arrivals:
        raise ReconcileError("No transfer to the on-chain owner was found, so nothing was changed.", 409)
    log = arrivals[-1]
    tx_hash = Web3.to_hex(log["transactionHash"]).lower()

    previous = asset.owner_wallet
    if BlockchainTransfer.query.filter_by(transaction_hash=tx_hash).first() is None:
        now = utcnow()
        db.session.add(BlockchainTransfer(
            blockchain_asset_id=asset.id, from_wallet=Web3.to_checksum_address(log["args"]["from"]),
            to_wallet=chain_owner, transaction_hash=tx_hash, block_number=log["blockNumber"], chain_id=w3.eth.chain_id,
            network=asset.blockchain_network, status="confirmed", requested_at=now, confirmed_at=now))
    asset.previous_owner, asset.owner_wallet, asset.status = previous, chain_owner, "transferred"
    db.session.commit()
    logger.warning("Ownership of token %s reconciled by an admin: %s -> %s (%s)", asset.token_id, previous, chain_owner, tx_hash)
    return {"changed": True, "owner": chain_owner}
