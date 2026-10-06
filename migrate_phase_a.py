#!/usr/bin/env python
"""
Phase A Migration: Add platform_card_id and blockchain asset tables
Run with: python migrate_phase_a.py
"""

from app import create_app, db
from app.models import CollectibleCard, BlockchainAsset, BlockchainTransfer

def migrate():
    app = create_app()
    with app.app_context():
        print("Starting Phase A migration...")
        
        # Create tables
        print("Creating blockchain_assets table...")
        db.create_all()
        
        # Assign platform_card_ids to existing cards
        cards_without_id = CollectibleCard.query.filter(
            CollectibleCard.platform_card_id.is_(None)
        ).all()
        
        print(f"Found {len(cards_without_id)} cards without platform IDs")
        for card in cards_without_id:
            platform_id = f"CARD-{card.id:06d}"
            card.platform_card_id = platform_id
            print(f"  Assigned {platform_id} to card {card.id}: {card.card_name}")
        
        db.session.commit()
        print(f"Assigned platform IDs to {len(cards_without_id)} cards")
        
        print("\nPhase A migration complete!")
        print(f"Total cards in system: {CollectibleCard.query.count()}")
        print(f"Cards with platform IDs: {CollectibleCard.query.filter(CollectibleCard.platform_card_id.isnot(None)).count()}")
        print(f"Blockchain assets: {BlockchainAsset.query.count()}")

if __name__ == "__main__":
    migrate()
