"""Service to complete card verification and create blockchain assets."""

import logging
from flask import current_app
from ..extensions import db
from ..models import CollectibleVerification, BlockchainAsset, CollectibleCard, utcnow
from .card_identity_service import create_blockchain_asset

logger = logging.getLogger(__name__)


def complete_verification_and_create_blockchain_asset(verification: CollectibleVerification, seller_wallet: str = None) -> dict:
    """
    Complete card verification and automatically create blockchain asset.
    
    This is called when admin approves a card.
    
    Args:
        verification: The CollectibleVerification to complete
        seller_wallet: The seller's wallet address for blockchain ownership
        
    Returns:
        dict with keys: 'success', 'asset', 'message'
    """
    try:
        card = verification.collectible_card
        
        # Check if card already has a blockchain asset
        if card.blockchain_asset:
            return {
                'success': False,
                'asset': None,
                'message': 'Card already has a blockchain asset'
            }
        
        # Ensure card has platform ID
        if not card.platform_card_id:
            return {
                'success': False,
                'asset': None,
                'message': 'Card does not have a Platform Card ID'
            }
        
        # Get contract address from config
        contract_address = current_app.config.get('COLLECTIBLE_CONTRACT_ADDRESS')
        if not contract_address:
            logger.warning("COLLECTIBLE_CONTRACT_ADDRESS not configured - blockchain asset creation skipped")
            return {
                'success': False,
                'asset': None,
                'message': 'Blockchain is not configured'
            }
        
        # Only a wallet the seller has proven they control may own the token
        verified = card.product.seller.verified_wallet
        owner_wallet = seller_wallet or verified
        if not owner_wallet or owner_wallet != verified:
            logger.info(f"Seller {card.product.seller_id} has no verified wallet - blockchain asset deferred")
            return {
                'success': False,
                'asset': None,
                'message': 'The seller has not verified a wallet yet. The card will be registered on the blockchain as soon as they do.'
            }
        
        # Create blockchain asset
        try:
            blockchain_asset = create_blockchain_asset(
                collectible_card=card,
                owner_wallet=owner_wallet,
                contract_address=contract_address,
                network=current_app.config['CHAIN_NAME'].lower()
            )
            
            logger.info(f"Created blockchain asset for card {card.id} (Platform ID: {card.platform_card_id})")
            
            return {
                'success': True,
                'asset': blockchain_asset,
                'message': f'Blockchain asset created: Token (pending mint)'
            }
        except Exception as e:
            logger.error(f"Error creating blockchain asset: {str(e)}")
            return {
                'success': False,
                'asset': None,
                'message': f'Error creating blockchain asset: {str(e)}'
            }
        
    except Exception as e:
        logger.error(f"Error in complete_verification_and_create_blockchain_asset: {str(e)}", exc_info=True)
        return {
            'success': False,
            'asset': None,
            'message': f'Error: {str(e)}'
        }


def get_card_blockchain_status(collectible_card: CollectibleCard) -> dict:
    """
    Get the blockchain registration status of a card.
    
    Returns:
        dict with keys: 'status', 'asset', 'token_id', 'owner', 'network', 'message'
    """
    if not collectible_card.blockchain_asset:
        return {
            'status': 'not_registered',
            'asset': None,
            'token_id': None,
            'owner': None,
            'network': None,
            'message': 'Card is not yet registered on blockchain'
        }
    
    asset = collectible_card.blockchain_asset
    return {
        'status': asset.status,  # draft, minting, minted, transferring, transferred
        'asset': asset,
        'token_id': asset.token_id,
        'owner': asset.owner_wallet,
        'network': asset.blockchain_network,
        'message': f'Card registered: {asset.status.title()}'
    }
