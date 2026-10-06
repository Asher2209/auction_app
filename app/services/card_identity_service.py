"""Service for managing unique card identities and blockchain assets"""

from ..extensions import db
from ..models import CollectibleCard, BlockchainAsset, CollectibleVerification
from .qrcode_service import generate_platform_card_id


def assign_platform_card_id(collectible_card: CollectibleCard) -> str:
    """
    Assign a unique platform card ID to a card if it doesn't have one.
    
    Args:
        collectible_card: The CollectibleCard instance
    
    Returns:
        The assigned platform_card_id
    """
    if collectible_card.platform_card_id:
        return collectible_card.platform_card_id
    
    # Generate platform ID based on card's ID
    platform_id = generate_platform_card_id(collectible_card.id)
    collectible_card.platform_card_id = platform_id
    db.session.commit()
    
    return platform_id


def create_blockchain_asset(collectible_card: CollectibleCard, owner_wallet: str, 
                           contract_address: str, network: str = "sepolia") -> BlockchainAsset:
    """
    Create a blockchain asset record for a verified physical card.
    
    Args:
        collectible_card: The CollectibleCard to create asset for
        owner_wallet: The wallet address that will own the token
        contract_address: The smart contract address
        network: The blockchain network (default: sepolia)
    
    Returns:
        The created BlockchainAsset instance
    """
    # First ensure card has platform ID
    if not collectible_card.platform_card_id:
        assign_platform_card_id(collectible_card)
    
    # Check if asset already exists
    existing = BlockchainAsset.query.filter_by(collectible_card_id=collectible_card.id).first()
    if existing:
        return existing
    
    # Create new blockchain asset
    asset = BlockchainAsset(
        collectible_card_id=collectible_card.id,
        owner_wallet=owner_wallet,
        contract_address=contract_address,
        blockchain_network=network,
        status='draft'
    )
    
    db.session.add(asset)
    db.session.commit()
    
    return asset


def assign_token_id(blockchain_asset: BlockchainAsset, token_id: int) -> None:
    """
    Assign a blockchain token ID to an asset.
    
    Args:
        blockchain_asset: The BlockchainAsset instance
        token_id: The token ID from the blockchain
    """
    blockchain_asset.token_id = token_id
    blockchain_asset.status = 'minting'
    db.session.commit()


def mark_token_minted(blockchain_asset: BlockchainAsset, transaction_hash: str, 
                     block_number: int) -> None:
    """
    Mark a blockchain asset as successfully minted.
    
    Args:
        blockchain_asset: The BlockchainAsset instance
        transaction_hash: The mint transaction hash
        block_number: The block where the mint was included
    """
    blockchain_asset.mint_transaction_hash = transaction_hash
    blockchain_asset.mint_block_number = block_number
    blockchain_asset.status = 'minted'
    db.session.commit()


def check_card_already_listed(collectible_card: CollectibleCard) -> dict:
    """
    Check if a card is already in an active auction or has been sold.
    
    Returns:
        dict with keys: 'is_listed', 'auction_id', 'status', 'reason'
    """
    from ..models import Auction, Product
    
    product = collectible_card.product
    
    # Check for active auctions
    active_auction = Auction.query.filter(
        Auction.product_id == product.id,
        Auction.status.in_(['scheduled', 'active'])
    ).first()
    
    if active_auction:
        return {
            'is_listed': True,
            'auction_id': active_auction.id,
            'status': active_auction.status,
            'reason': f'Card is already in an {active_auction.status} auction'
        }
    
    # Check for previous sales
    closed_auction = Auction.query.filter(
        Auction.product_id == product.id,
        Auction.status == 'closed'
    ).first()
    
    if closed_auction:
        return {
            'is_listed': True,
            'auction_id': closed_auction.id,
            'status': 'closed',
            'reason': 'Card has already been sold in a previous auction'
        }
    
    return {
        'is_listed': False,
        'auction_id': None,
        'status': None,
        'reason': None
    }


def validate_card_ownership(collectible_card: CollectibleCard, seller_wallet: str) -> dict:
    """
    Validate that seller owns the card on blockchain.
    
    Returns:
        dict with keys: 'valid', 'reason'
    """
    blockchain_asset = collectible_card.blockchain_asset
    
    if not blockchain_asset:
        return {
            'valid': False,
            'reason': 'Card has not been registered on blockchain yet'
        }
    
    if blockchain_asset.status != 'minted':
        return {
            'valid': False,
            'reason': f'Card blockchain asset is in {blockchain_asset.status} state, not yet fully minted'
        }
    
    if blockchain_asset.owner_wallet.lower() != seller_wallet.lower():
        return {
            'valid': False,
            'reason': f'Card is owned by {blockchain_asset.owner_wallet}, not {seller_wallet}'
        }
    
    return {
        'valid': True,
        'reason': None
    }
