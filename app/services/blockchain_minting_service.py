"""Service for minting card tokens on blockchain"""

from decimal import Decimal
from flask import current_app
from web3 import Web3
from sqlalchemy import update

from ..extensions import db
from ..models import BlockchainAsset, utcnow
from .blockchain_service import get_web3, crypto_enabled
import json
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "build" / "CollectibleCardToken.json"


class MintError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _abi():
    """Load contract ABI"""
    try:
        return json.loads(ARTIFACT.read_text())["abi"]
    except (FileNotFoundError, json.JSONDecodeError):
        # Fallback to AuctionPayment ABI if token contract not compiled yet
        payment_artifact = ARTIFACT.parent / "AuctionPayment.json"
        return json.loads(payment_artifact.read_text())["abi"]


def _contract(w3, contract_address):
    """Get contract instance"""
    return w3.eth.contract(
        address=Web3.to_checksum_address(contract_address),
        abi=_abi()
    )


def initiate_mint(blockchain_asset, minter_wallet):
    """
    Prepare minting transaction data.
    
    Args:
        blockchain_asset: BlockchainAsset to mint
        minter_wallet: Wallet initiating mint (seller)
    
    Returns:
        dict with transaction data to send to blockchain
    """
    if not crypto_enabled():
        raise MintError("Blockchain is not configured", 503)
    
    if blockchain_asset.status != 'draft':
        raise MintError(f"Asset must be in draft state, not {blockchain_asset.status}")
    
    collectible_card = blockchain_asset.collectible_card
    if not collectible_card.platform_card_id:
        raise MintError("Card does not have a platform ID")
    
    # Extract numeric platform ID (CARD-000123 -> 123)
    platform_numeric = int(collectible_card.platform_card_id.split('-')[1])
    
    w3 = get_web3()
    contract = _contract(w3, blockchain_asset.contract_address)
    
    # Prepare mint transaction data
    card_name = collectible_card.card_name or "Unknown Card"
    owner_wallet = Web3.to_checksum_address(blockchain_asset.owner_wallet)
    
    # Build transaction data
    data = contract.encode_abi(
        "mint",
        args=[platform_numeric, owner_wallet, card_name]
    )
    
    return {
        "to": blockchain_asset.contract_address,
        "data": data,
        "from": minter_wallet,
        "value": "0x0"
    }


def submit_mint(blockchain_asset, tx_hash_raw):
    """
    Record minting transaction submission.
    
    Args:
        blockchain_asset: BlockchainAsset being minted
        tx_hash_raw: Transaction hash from blockchain
    
    Returns:
        Updated BlockchainAsset
    """
    tx_hash = tx_hash_raw.strip().lower() if isinstance(tx_hash_raw, str) else ""
    
    # Validate transaction hash format
    if not tx_hash.startswith("0x") or len(tx_hash) != 66:
        raise MintError("Invalid transaction hash format")
    
    if blockchain_asset.status != 'draft':
        raise MintError("Asset must be in draft state to submit mint")
    
    # Update status to minting
    blockchain_asset.status = 'minting'
    blockchain_asset.mint_transaction_hash = tx_hash
    blockchain_asset.updated_at = utcnow()
    
    db.session.commit()
    
    return blockchain_asset


def verify_mint(blockchain_asset, now=None):
    """
    Verify minting transaction on blockchain.
    
    Args:
        blockchain_asset: BlockchainAsset to verify
        now: Current timestamp (for testing)
    
    Returns:
        dict with verification result: {status, token_id, block_number, confirmations}
    """
    now = now or utcnow()
    
    if not crypto_enabled():
        return {"status": "pending", "reason": "Blockchain not available"}
    
    if not blockchain_asset.mint_transaction_hash:
        return {"status": "pending", "reason": "No transaction hash yet"}
    
    w3 = get_web3()
    
    try:
        # Get transaction receipt
        receipt = w3.eth.get_transaction_receipt(blockchain_asset.mint_transaction_hash)
        
        if not receipt:
            return {"status": "pending", "reason": "Transaction not yet mined"}
        
        # Check if transaction succeeded
        if receipt["status"] != 1:
            return {
                "status": "failed",
                "reason": "Transaction reverted on blockchain"
            }
        
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
        
        # Successfully minted!
        return {
            "status": "confirmed",
            "block_number": receipt["blockNumber"],
            "confirmations": confirmations,
            "transaction_hash": blockchain_asset.mint_transaction_hash
        }
        
    except Exception as e:
        return {
            "status": "error",
            "reason": str(e)
        }


def complete_mint(blockchain_asset, token_id, block_number):
    """
    Mark minting as complete and assign token ID.
    
    Args:
        blockchain_asset: BlockchainAsset that was minted
        token_id: Token ID from blockchain
        block_number: Block where mint was confirmed
    """
    blockchain_asset.token_id = token_id
    blockchain_asset.mint_block_number = block_number
    blockchain_asset.status = 'minted'
    blockchain_asset.updated_at = utcnow()
    
    db.session.commit()
    
    return blockchain_asset
