"""Read-only checks that the MySQL owner of a card token matches the owner recorded on-chain.

The chain is the ledger of record. A mismatch is reported as OWNERSHIP SYNC ERROR and the
database is never silently overwritten to make it go away.
"""
import logging
from dataclasses import dataclass

from web3 import Web3
from web3.exceptions import ContractLogicError

from . import blockchain_service

logger = logging.getLogger(__name__)

OWNER_OF_ABI = [{
    "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
    "name": "ownerOf",
    "outputs": [{"internalType": "address", "name": "", "type": "address"}],
    "stateMutability": "view",
    "type": "function",
}]

IN_SYNC = "in_sync"
SYNC_ERROR = "sync_error"
UNVERIFIED = "unverified"  # the chain could not be consulted; says nothing about a mismatch


@dataclass
class OwnershipCheck:
    status: str
    db_owner: str | None
    onchain_owner: str | None = None
    reason: str | None = None


def check_ownership_sync(asset):
    """Compare asset.owner_wallet with ownerOf(token_id) on the asset's contract."""
    db_owner = asset.owner_wallet
    if asset.token_id is None:
        return OwnershipCheck(UNVERIFIED, db_owner, reason="The card has no token yet.")
    w3 = blockchain_service.get_web3()
    if w3 is None:
        return OwnershipCheck(UNVERIFIED, db_owner, reason="No blockchain connection is configured.")
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(asset.contract_address), abi=OWNER_OF_ABI)
        onchain_owner = contract.functions.ownerOf(asset.token_id).call()
    except ContractLogicError:
        logger.error("OWNERSHIP SYNC ERROR: token %s does not exist on %s", asset.token_id, asset.contract_address)
        return OwnershipCheck(SYNC_ERROR, db_owner, reason="The token does not exist on the blockchain.")
    except Exception as exc:  # RPC down, timeout, bad address: the chain simply could not be read
        logger.warning("ownerOf lookup failed for token %s: %s", asset.token_id, exc)
        return OwnershipCheck(UNVERIFIED, db_owner, reason="The blockchain could not be reached.")

    if onchain_owner.lower() != (db_owner or "").lower():
        logger.error("OWNERSHIP SYNC ERROR: token %s database owner %s, on-chain owner %s",
                     asset.token_id, db_owner, onchain_owner)
        return OwnershipCheck(SYNC_ERROR, db_owner, onchain_owner,
                              "The recorded owner does not match the on-chain owner.")
    return OwnershipCheck(IN_SYNC, db_owner, onchain_owner)
