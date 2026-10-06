#!/usr/bin/env python
"""Phase A Migration: Add platform_card_id and blockchain asset tables"""

from app import create_app, db
from app.models import CollectibleCard, BlockchainAsset, BlockchainTransfer
from sqlalchemy import text, inspect

def migrate():
    app = create_app()
    with app.app_context():
        print("Starting Phase A migration...")
        
        # Create all new tables
        print("Creating new tables...")
        db.create_all()
        
        # Check if platform_card_id column exists, if not add it
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('collectible_cards')]
        
        if 'platform_card_id' not in columns:
            print("Adding platform_card_id column to collectible_cards table...")
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE collectible_cards ADD COLUMN platform_card_id VARCHAR(20)'))
        
        # Assign platform_card_ids to existing cards
        cards_without_id = CollectibleCard.query.filter(
            CollectibleCard.platform_card_id.is_(None)
        ).all()
        
        print(f"Found {len(cards_without_id)} cards without platform IDs")
        for card in cards_without_id:
            platform_id = f"CARD-{card.id:06d}"
            card.platform_card_id = platform_id
            print(f"  Assigned {platform_id} to card {card.id}: {card.card_name}")
        
        if cards_without_id:
            db.session.commit()
            print(f"Assigned platform IDs to {len(cards_without_id)} cards")
        
        print("\nPhase A migration complete!")
        print(f"Total cards in system: {CollectibleCard.query.count()}")
        cards_with_id = CollectibleCard.query.filter(CollectibleCard.platform_card_id.isnot(None)).count()
        print(f"Cards with platform IDs: {cards_with_id}")
        print(f"Blockchain assets: {BlockchainAsset.query.count()}")

if __name__ == "__main__":
    migrate()
