"""Service for transferring card ownership on blockchain"""

from flask import current_app
from web3 import Web3
from datetime import timedelta

from ..extensions import db
from ..models import BlockchainAsset, BlockchainTransfer, utcnow
from .blockchain_service import get_web3, crypto_enabled
import json
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "build" / "CollectibleCardToken.json"


class TransferError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _abi():
    """Load contract ABI"""
    try:
        return json.loads(ARTIFACT.read_text())["abi"]
    except (FileNotFoundError, json.JSONDecodeError):
        payment_artifact = ARTIFACT.parent / "AuctionPayment.json"
        return json.loads(payment_artifact.read_text())["abi"]


def _contract(w3, contract_address):
    """Get contract instance"""
    return w3.eth.contract(
        address=Web3.to_checksum_address(contract_address),
        abi=_abi()
    )


def initiate_transfer(blockchain_asset, buyer_wallet, auction_id):
    """
    Prepare ownership transfer transaction.
    
    Args:
        blockchain_asset: BlockchainAsset to transfer
        buyer_wallet: New owner wallet address
        auction_id: Auction that triggered transfer
    
    Returns:
        dict with transaction data
    """
    if not crypto_enabled():
        raise TransferError("Blockchain not configured", 503)
    
    if blockchain_asset.status != 'minted':
        raise TransferError(f"Can only transfer minted tokens, not {blockchain_asset.status}")
    
    if not blockchain_asset.token_id:
        raise TransferError("Token does not have a token_id")
    
    w3 = get_web3()
    contract = _contract(w3, blockchain_asset.contract_address)
    
    # Prepare transfer transaction
    buyer_wallet_checksum = Web3.to_checksum_address(buyer_wallet)
    
    data = contract.encode_abi(
        "transferCard",
        args=[blockchain_asset.token_id, buyer_wallet_checksum, auction_id]
    )
    
    return {
        "to": blockchain_asset.contract_address,
        "data": data,
        "from": blockchain_asset.owner_wallet,
        "value": "0x0"
    }


def submit_transfer(blockchain_asset, buyer_wallet, tx_hash_raw, auction_id):
    """
    Record transfer transaction submission.
    
    Args:
        blockchain_asset: BlockchainAsset being transferred
        buyer_wallet: New owner wallet
        tx_hash_raw: Transaction hash
        auction_id: Auction ID
    
    Returns:
        BlockchainTransfer record
    """
    tx_hash = tx_hash_raw.strip().lower() if isinstance(tx_hash_raw, str) else ""
    
    if not tx_hash.startswith("0x") or len(tx_hash) != 66:
        raise TransferError("Invalid transaction hash")
    
    # Create transfer record
    transfer = BlockchainTransfer(
        blockchain_asset_id=blockchain_asset.id,
        from_wallet=blockchain_asset.owner_wallet,
        to_wallet=buyer_wallet,
        auction_id=auction_id,
        transaction_hash=tx_hash,
        network=blockchain_asset.blockchain_network,
        status='pending'
    )
    
    # Mark asset as transferring
    blockchain_asset.status = 'transferring'
    blockchain_asset.previous_owner = blockchain_asset.owner_wallet
    blockchain_asset.updated_at = utcnow()
    
    db.session.add(transfer)
    db.session.commit()
    
    return transfer


def verify_transfer(blockchain_transfer, now=None):
    """
    Verify ownership transfer on blockchain.
    
    Args:
        blockchain_transfer: BlockchainTransfer to verify
        now: Current timestamp
    
    Returns:
        dict with verification result
    """
    now = now or utcnow()
    
    if not crypto_enabled():
        return {"status": "pending", "reason": "Blockchain not available"}
    
    if not blockchain_transfer.transaction_hash:
        return {"status": "pending", "reason": "No transaction hash"}
    
    w3 = get_web3()
    
    try:
        # Get transaction receipt
        receipt = w3.eth.get_transaction_receipt(blockchain_transfer.transaction_hash)
        
        if not receipt:
            # Check timeout
            timeout = timedelta(minutes=current_app.config.get("CRYPTO_NOT_FOUND_TIMEOUT_MINUTES", 30))
            if blockchain_transfer.requested_at and now - blockchain_transfer.requested_at > timeout:
                return {"status": "failed", "reason": "Transaction not found within timeout"}
            return {"status": "pending", "reason": "Transaction not yet mined"}
        
        # Check status
        if receipt["status"] != 1:
            return {"status": "failed", "reason": "Transaction reverted"}
        
        # Check confirmations
        current_block = w3.eth.block_number
        confirmations = current_block - receipt["blockNumber"] + 1
        required = current_app.config.get("CONFIRMATIONS_REQUIRED", 1)
        
        if confirmations < required:
            return {
                "status": "pending",
                "reason": f"Waiting for confirmations ({confirmations}/{required})",
                "confirmations": confirmations
            }
        
        # Transfer confirmed!
        return {
            "status": "confirmed",
            "block_number": receipt["blockNumber"],
            "confirmations": confirmations
        }
        
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def complete_transfer(blockchain_transfer, block_number):
    """
    Mark transfer as complete and update ownership.
    
    Args:
        blockchain_transfer: BlockchainTransfer that was confirmed
        block_number: Block where transfer was confirmed
    """
    blockchain_asset = blockchain_transfer.blockchain_asset
    
    # Update transfer record
    blockchain_transfer.block_number = block_number
    blockchain_transfer.confirmed_at = utcnow()
    blockchain_transfer.status = 'confirmed'
    
    # Update asset ownership
    blockchain_asset.owner_wallet = blockchain_transfer.to_wallet
    blockchain_asset.status = 'transferred'
    blockchain_asset.updated_at = utcnow()
    
    db.session.commit()
    
    return blockchain_transfer


def get_ownership_history(blockchain_asset):
    """
    Get complete ownership history for an asset.
    
    Args:
        blockchain_asset: BlockchainAsset
    
    Returns:
        List of transfers
    """
    return BlockchainTransfer.query.filter_by(
        blockchain_asset_id=blockchain_asset.id
    ).order_by(BlockchainTransfer.requested_at).all()
