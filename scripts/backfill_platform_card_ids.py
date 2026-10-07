"""
Backfill Platform Card IDs for existing collectible cards

This migration assigns Platform Card IDs to any cards that don't have them yet.
Platform Card IDs are in the format CARD-XXXXXX where XXXXXX is the card's ID.
"""

from app.extensions import db
from app.models import CollectibleCard
from app.services.card_identity_service import assign_platform_card_id
from app.services.qrcode_service import save_qr_code_to_file


def regenerate_all_qr_codes():
    """Rewrite every card's QR file (use after APP_BASE_URL or the public card route changes)"""
    cards = CollectibleCard.query.filter(CollectibleCard.platform_card_id.isnot(None)).all()
    for card in cards:
        save_qr_code_to_file(card.platform_card_id, card.id)
    print(f"Regenerated {len(cards)} QR codes")


def backfill_platform_card_ids(regenerate_qr=False):
    """Assign platform card IDs and generate QR codes for cards missing them"""
    if regenerate_qr:
        regenerate_all_qr_codes()

    # Find all cards without platform IDs
    cards_without_ids = CollectibleCard.query.filter_by(platform_card_id=None).all()
    
    if not cards_without_ids:
        print("✓ All cards already have Platform Card IDs")
        return
    
    print(f"Found {len(cards_without_ids)} cards without Platform Card IDs")
    
    for i, card in enumerate(cards_without_ids, 1):
        try:
            # Assign platform card ID
            platform_card_id = assign_platform_card_id(card)
            
            # Generate QR code
            try:
                qr_path = save_qr_code_to_file(platform_card_id, card.id)
                print(f"  [{i}/{len(cards_without_ids)}] ✓ {platform_card_id} - QR code generated")
            except Exception as qr_error:
                print(f"  [{i}/{len(cards_without_ids)}] ⚠ {platform_card_id} - QR code generation failed: {qr_error}")
                
        except Exception as e:
            print(f"  [{i}/{len(cards_without_ids)}] ✗ Failed to process card {card.id}: {e}")
    
    print(f"\nBackfill complete! Assigned Platform Card IDs to {len(cards_without_ids)} cards.")


if __name__ == '__main__':
    import sys
    from app import create_app
    app = create_app()
    with app.app_context():
        backfill_platform_card_ids(regenerate_qr="--regenerate-qr" in sys.argv)
