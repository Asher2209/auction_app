"""Enhanced minting service with comprehensive error handling."""

import logging
from typing import Dict, Any

from flask import current_app
from web3 import Web3

from ..extensions import db
from ..models import BlockchainAsset, utcnow
from .blockchain_service import get_web3, crypto_enabled
from .blockchain_service_enhanced import (
    BlockchainError, TransactionError, ValidationError, 
    log_transaction_event, log_blockchain_error
)
import json
from pathlib import Path

logger = logging.getLogger(__name__)

ARTIFACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "build" / "CollectibleCardToken.json"

MIN_GAS_FOR_MINT = 150000


class MintError(BlockchainError):
    """Minting-specific error"""
    pass


def _abi():
    """Load contract ABI with error handling"""
    try:
        artifact = json.loads(ARTIFACT.read_text())
        if "abi" not in artifact:
            raise ValueError("ABI not found in artifact")
        return artifact["abi"]
    except FileNotFoundError:
        logger.error(f"Contract artifact not found at {ARTIFACT}")
        raise MintError("Smart contract not available. Please try again later.", 503)
    except Exception as e:
        logger.error(f"Error loading contract ABI: {str(e)}", exc_info=True)
        raise MintError("Unable to load contract. Please try again later.", 503)


def _contract(w3, contract_address: str):
    """Get contract instance with validation"""
    try:
        if not isinstance(contract_address, str) or not contract_address.startswith('0x'):
            raise ValidationError(f"Invalid contract address: {contract_address}")
        
        checksum_address = Web3.to_checksum_address(contract_address)
        return w3.eth.contract(address=checksum_address, abi=_abi())
    except Exception as e:
        logger.error(f"Error getting contract instance: {str(e)}")
        raise MintError("Failed to load contract. Please try again later.", 503)


def initiate_mint(blockchain_asset: BlockchainAsset, minter_wallet: str) -> Dict[str, Any]:
    """Prepare minting transaction data with validation."""
    try:
        if not crypto_enabled():
            raise MintError("Blockchain is not configured.", 503)
        
        if blockchain_asset.status != 'draft':
            raise ValidationError(f"Asset must be in draft state, not {blockchain_asset.status}")
        
        card = blockchain_asset.collectible_card
        if not card.platform_card_id:
            raise ValidationError("Card does not have a platform ID (format: CARD-XXXXXX)")
        
        try:
            parts = card.platform_card_id.split('-')
            if len(parts) != 2 or parts[0] != 'CARD':
                raise ValueError("Invalid platform ID format")
            platform_numeric = int(parts[1])
        except (ValueError, IndexError) as e:
            raise ValidationError(f"Invalid card platform ID: {card.platform_card_id}")
        
        w3 = get_web3()
        contract = _contract(w3, blockchain_asset.contract_address)
        
        card_name = card.card_name or "Collectible Card"
        owner_wallet = Web3.to_checksum_address(blockchain_asset.owner_wallet)
        
        data = contract.encode_abi("mint", args=[platform_numeric, owner_wallet, card_name])
        
        log_transaction_event("pending", "mint_prepare", {
            "asset_id": blockchain_asset.id,
            "platform_id": card.platform_card_id
        })
        
        return {
            "to": blockchain_asset.contract_address,
            "data": data,
            "from": minter_wallet,
            "value": "0x0"
        }
    
    except (ValidationError, MintError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error in initiate_mint: {str(e)}", exc_info=True)
        raise MintError("An unexpected error occurred. Please try again.", 500)


def submit_mint(blockchain_asset: BlockchainAsset, tx_hash_raw: str) -> BlockchainAsset:
    """Record minting transaction submission with validation."""
    try:
        if not isinstance(tx_hash_raw, str):
            raise ValidationError("Transaction hash must be a string")
        
        tx_hash = tx_hash_raw.strip().lower()
        
        if not tx_hash.startswith("0x") or len(tx_hash) != 66:
            raise ValidationError("Invalid transaction hash format. Expected 0x followed by 64 hex characters.")
        
        if blockchain_asset.status != 'draft':
            raise ValidationError(f"Asset must be in draft state, not {blockchain_asset.status}")
        
        blockchain_asset.status = 'minting'
        blockchain_asset.mint_transaction_hash = tx_hash
        blockchain_asset.updated_at = utcnow()
        
        db.session.commit()
        
        log_transaction_event(tx_hash, "mint_submit", {"asset_id": blockchain_asset.id})
        logger.info(f"Minting transaction submitted: {tx_hash} for asset {blockchain_asset.id}")
        
        return blockchain_asset
    
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error submitting mint: {str(e)}", exc_info=True)
        db.session.rollback()
        raise MintError("Failed to submit mint transaction. Please try again.", 500)


def verify_mint(blockchain_asset: BlockchainAsset, now=None) -> Dict[str, Any]:
    """Verify minting transaction on blockchain with error handling."""
    try:
        if not crypto_enabled():
            return {"status": "pending", "reason": "Blockchain not available"}
        
        if not blockchain_asset.mint_transaction_hash:
            return {"status": "pending", "reason": "No transaction hash yet"}
        
        w3 = get_web3()
        
        try:
            receipt = w3.eth.get_transaction_receipt(blockchain_asset.mint_transaction_hash)
        except Exception as e:
            logger.warning(f"Failed to get receipt: {str(e)}")
            return {"status": "pending", "reason": "Transaction not yet mined on blockchain"}
        
        if receipt is None:
            return {"status": "pending", "reason": "Transaction not yet mined on blockchain"}
        
        if receipt.get("status") != 1:
            logger.error(f"Transaction reverted: {blockchain_asset.mint_transaction_hash}")
            return {"status": "failed", "reason": "Transaction reverted on blockchain"}
        
        current_block = w3.eth.block_number
        confirmations = current_block - receipt["blockNumber"] + 1
        required = current_app.config.get("CONFIRMATIONS_REQUIRED", 1)
        
        if confirmations < required:
            return {
                "status": "pending",
                "reason": f"Waiting for confirmations ({confirmations}/{required})",
                "confirmations": confirmations
            }
        
        logger.info(f"Mint confirmed for asset {blockchain_asset.id}: {confirmations} confirmations")
        log_transaction_event(blockchain_asset.mint_transaction_hash, "mint_confirmed",
                            {"asset_id": blockchain_asset.id, "confirmations": confirmations})
        
        return {
            "status": "confirmed",
            "block_number": receipt["blockNumber"],
            "confirmations": confirmations,
            "transaction_hash": blockchain_asset.mint_transaction_hash
        }
    
    except Exception as e:
        logger.error(f"Unexpected error verifying mint: {str(e)}", exc_info=True)
        return {"status": "error", "reason": "An error occurred while verifying the transaction"}


def complete_mint(blockchain_asset: BlockchainAsset, token_id: int, block_number: int) -> BlockchainAsset:
    """Mark minting as complete and assign token ID."""
    try:
        if not isinstance(token_id, int) or token_id <= 0:
            raise ValidationError(f"Invalid token ID: {token_id}")
        
        blockchain_asset.token_id = token_id
        blockchain_asset.mint_block_number = block_number
        blockchain_asset.status = 'minted'
        blockchain_asset.updated_at = utcnow()
        
        db.session.commit()
        
        log_transaction_event(blockchain_asset.mint_transaction_hash or "unknown", "mint_complete",
                            {"asset_id": blockchain_asset.id, "token_id": token_id})
        
        logger.info(f"Minting complete for asset {blockchain_asset.id}: token_id={token_id}")
        
        return blockchain_asset
    
    except Exception as e:
        logger.error(f"Error completing mint: {str(e)}", exc_info=True)
        db.session.rollback()
        raise MintError("Failed to complete minting. Please try again.", 500)
