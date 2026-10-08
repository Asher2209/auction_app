"""Routes for public collectible card views and verification"""

from flask import render_template, abort, request
from ...models import CollectibleCard, CollectibleVerification, BlockchainAsset, utcnow
from ...services import blockchain_service, ownership_transfer_service, qrcode_service
from . import bp


@bp.route("/card-verification/<platform_card_id>", methods=["GET"])
def verify_card(platform_card_id: str):
    """
    Public card verification page - accessible via QR code
    Shows card details, verification status, and blockchain identity
    """
    collectible_card = CollectibleCard.query.filter_by(platform_card_id=platform_card_id).first_or_404()
    product = collectible_card.product
    verification = product.collectible_verification
    blockchain_asset = collectible_card.blockchain_asset
    is_verified = verification is not None and verification.verification_status == 'verified'
    
    # Get card images
    card_images = collectible_card.images
    
    # Get type-specific details
    type_details = collectible_card.get_type_details() if collectible_card.type_details else {}
    
    # Get seller info (limited to public info only)
    seller = product.seller
    
    # Check if card is in active auction
    from ...models import Auction
    active_auction = Auction.query.filter(
        Auction.product_id == product.id,
        Auction.status.in_(['scheduled', 'active'])
    ).first()
    
    # Generate QR code for display
    qr_svg = qrcode_service.generate_qr_code_svg(platform_card_id)
    
    return render_template(
        'collectibles/card_verification.html',
        collectible_card=collectible_card,
        product=product,
        verification=verification,
        is_verified=is_verified,
        transfers=ownership_transfer_service.history(blockchain_asset) if blockchain_asset else [],
        tx_url=blockchain_service.explorer_url,
        blockchain_asset=blockchain_asset,
        card_images=card_images,
        type_details=type_details,
        seller=seller,
        active_auction=active_auction,
        qr_svg=qr_svg,
        platform_card_id=platform_card_id,
        utcnow=utcnow
    )
