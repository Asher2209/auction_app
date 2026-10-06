#!/usr/bin/env python
"""
Seed script to generate 20 dummy collectible cards for testing
Includes realistic card data, images, and verification records
"""

import os
import sys
from io import BytesIO
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import random

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app
from app.extensions import db
from app.models import (
    User, Product, CollectibleCard, CardType, CardImage,
    CardVerificationHistory, CollectibleVerification, utcnow
)

app = create_app()

# Card data templates
POKEMON_CARDS = [
    {'name': 'Charizard Base Set', 'hp': 120, 'holo': 'holographic', 'set': 'Base Set', 'number': '4/102', 'year': 1999, 'is_first': True},
    {'name': 'Blastoise Base Set', 'hp': 100, 'holo': 'holographic', 'set': 'Base Set', 'number': '2/102', 'year': 1999, 'is_first': True},
    {'name': 'Venusaur Base Set', 'hp': 80, 'holo': 'holographic', 'set': 'Base Set', 'number': '15/102', 'year': 1999, 'is_first': False},
    {'name': 'Mewtwo Base Set', 'hp': 60, 'holo': 'holographic', 'set': 'Base Set', 'number': '10/102', 'year': 1999, 'is_first': True},
    {'name': 'Gyarados Base Set', 'hp': 130, 'holo': 'non-holographic', 'set': 'Base Set', 'number': '6/102', 'year': 1999, 'is_first': False},
]

FOOTBALL_CARDS = [
    {'name': 'Lionel Messi PSA 10', 'player': 'Lionel Messi', 'team': 'Paris Saint-Germain', 'league': 'Ligue 1', 'year': 2022, 'is_rookie': False},
    {'name': 'Cristiano Ronaldo Manchester United', 'player': 'Cristiano Ronaldo', 'team': 'Manchester United', 'league': 'Premier League', 'year': 2003, 'is_rookie': True},
    {'name': 'Mohamed Salah Liverpool', 'player': 'Mohamed Salah', 'team': 'Liverpool', 'league': 'Premier League', 'year': 2017, 'is_rookie': False},
    {'name': 'Kylian Mbappé PSG Rookie', 'player': 'Kylian Mbappé', 'team': 'Paris Saint-Germain', 'league': 'Ligue 1', 'year': 2017, 'is_rookie': True},
    {'name': 'Robert Lewandowski Bayern Munich', 'player': 'Robert Lewandowski', 'team': 'Bayern Munich', 'league': 'Bundesliga', 'year': 2010, 'is_rookie': False},
]

CONDITIONS = ['Poor', 'Fair', 'Good', 'Very Good', 'Excellent', 'Near Mint', 'Mint']
GRADING_COMPANIES = ['PSA', 'Beckett', 'CGC', None]
GRADES = ['1.0', '2.5', '4.5', '6.5', '7.5', '8.5', '9.0', '9.5', '10.0']

def create_placeholder_image(card_name, card_type='pokemon'):
    """Create a simple placeholder card image"""
    width, height = 400, 600

    if card_type == 'pokemon':
        bg_color = (255, 200, 100)  # Orange for Pokemon
        accent_color = (255, 150, 0)
    else:
        bg_color = (100, 150, 200)  # Blue for Football
        accent_color = (50, 100, 200)

    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Draw border
    draw.rectangle([5, 5, width-5, height-5], outline=accent_color, width=3)

    # Draw center text with card name
    text_y = height // 2 - 40
    for line in [card_name[:20], card_name[20:40] if len(card_name) > 20 else '']:
        if line:
            draw.text((width//2, text_y), line, fill=(50, 50, 50), anchor='mm')
            text_y += 50

    # Draw card type at bottom
    draw.text((width//2, height - 50), card_type.upper(), fill=(255, 255, 255), anchor='mm')

    return img

def save_card_image(card_name, card_type='pokemon'):
    """Save a placeholder image and return the filename"""
    img = create_placeholder_image(card_name, card_type)

    # Create uploads directory if needed
    uploads_dir = Path('app/static/uploads')
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Save with timestamp to ensure uniqueness
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    filename = f'card_{timestamp}.png'
    filepath = uploads_dir / filename

    img.save(filepath, 'PNG')
    return filename

def seed_pokemon_cards(seller_user, card_type):
    """Seed Pokemon trading cards"""
    conditions = random.sample(CONDITIONS, len(POKEMON_CARDS))

    for idx, card_data in enumerate(POKEMON_CARDS):
        # Create placeholder image
        image_filename = save_card_image(card_data['name'], 'pokemon')

        # Create Product
        product = Product(
            seller_id=seller_user.id,
            title=card_data['name'],
            description=f"Collectible Pokemon card from {card_data['set']} set. {card_data['name']} in {conditions[idx]} condition.",
            starting_price=random.randint(100, 5000) / 100,
            auction_start=utcnow(),
            auction_end=utcnow(),
            approval_status='pending',
        )
        db.session.add(product)
        db.session.flush()

        # Create ProductImage
        from app.models import ProductImage
        product_image = ProductImage(product_id=product.id, path=image_filename)
        db.session.add(product_image)

        # Create CollectibleCard
        is_graded = random.choice([True, False, False, False])  # 25% graded
        grading_company = random.choice(GRADING_COMPANIES)

        collectible_card = CollectibleCard(
            product_id=product.id,
            card_type_id=card_type.id,
            card_name=card_data['name'],
            manufacturer='The Pokemon Company',
            set_name=card_data['set'],
            set_code='BS',
            release_year=card_data['year'],
            card_number=card_data['number'],
            rarity=random.choice(['Common', 'Uncommon', 'Rare', 'Holo Rare']),
            condition=conditions[idx],
            condition_notes=f"Well-preserved card with {conditions[idx]} condition. See images for details.",
            language='English',
            country='USA',
            is_graded=is_graded,
            grading_company=grading_company if is_graded else None,
            grade=random.choice(GRADES) if is_graded else None,
            certification_number=f"PSA-{random.randint(100000, 999999)}" if is_graded else None,
            estimated_value=random.randint(50, 10000) / 100,
            type_details={
                'pokemon_name': card_data['name'].split()[0],
                'pokemon_hp': card_data['hp'],
                'pokemon_holo_type': card_data['holo'],
                'pokemon_first_edition': card_data['is_first'],
                'pokemon_shadowless': False,
                'pokemon_promo': False,
                'pokemon_illustrator': 'Ken Sugimori',
            }
        )
        db.session.add(collectible_card)
        db.session.flush()

        # Create CardImage
        card_image = CardImage(
            collectible_card_id=collectible_card.id,
            image_type='front',
            path=image_filename
        )
        db.session.add(card_image)

        # Create CollectibleVerification
        verification_status = random.choice(['pending', 'verified', 'more_info_needed'])
        verification = CollectibleVerification(
            product_id=product.id,
            collectible_card_id=collectible_card.id,
            is_graded=is_graded,
            verification_status=verification_status,
            created_at=utcnow(),
            submission_count=1 if verification_status != 'more_info_needed' else random.randint(1, 3),
        )
        db.session.add(verification)
        db.session.flush()

        # Create verification history
        history = CardVerificationHistory(
            verification_id=verification.id,
            previous_status='pending',
            new_status=verification_status,
            change_reason='Initial submission',
            created_at=utcnow()
        )
        db.session.add(history)

        print(f"✓ Created Pokemon card: {card_data['name']}")

def seed_football_cards(seller_user, card_type):
    """Seed Football trading cards"""
    conditions = random.sample(CONDITIONS, len(FOOTBALL_CARDS))

    for idx, card_data in enumerate(FOOTBALL_CARDS):
        # Create placeholder image
        image_filename = save_card_image(card_data['name'], 'football')

        # Create Product
        product = Product(
            seller_id=seller_user.id,
            title=card_data['name'],
            description=f"Collectible football card of {card_data['player']} from {card_data['team']}. {conditions[idx]} condition.",
            starting_price=random.randint(50, 2000) / 100,
            auction_start=utcnow(),
            auction_end=utcnow(),
            approval_status='pending',
        )
        db.session.add(product)
        db.session.flush()

        # Create ProductImage
        from app.models import ProductImage
        product_image = ProductImage(product_id=product.id, path=image_filename)
        db.session.add(product_image)

        # Create CollectibleCard
        is_graded = random.choice([True, False, False])  # ~33% graded
        grading_company = random.choice(GRADING_COMPANIES)

        collectible_card = CollectibleCard(
            product_id=product.id,
            card_type_id=card_type.id,
            card_name=card_data['name'],
            manufacturer=random.choice(['Panini', 'Topps', 'Upper Deck']),
            set_name=f"{card_data['team']} Official Collection",
            set_code=card_data['team'][:3].upper(),
            release_year=card_data['year'],
            card_number=f"{random.randint(1, 500)}",
            rarity=random.choice(['Common', 'Uncommon', 'Rare', 'Super Rare']),
            condition=conditions[idx],
            condition_notes=f"{card_data['player']} card in {conditions[idx]} condition from {card_data['year']}.",
            language='English',
            country='USA',
            is_graded=is_graded,
            grading_company=grading_company if is_graded else None,
            grade=random.choice(GRADES) if is_graded else None,
            certification_number=f"BVG-{random.randint(100000, 999999)}" if is_graded else None,
            estimated_value=random.randint(25, 5000) / 100,
            type_details={
                'football_player_name': card_data['player'],
                'football_team': card_data['team'],
                'football_league': card_data['league'],
                'football_season': str(card_data['year']),
                'football_is_rookie': card_data['is_rookie'],
                'football_is_autograph': False,
            }
        )
        db.session.add(collectible_card)
        db.session.flush()

        # Create CardImage
        card_image = CardImage(
            collectible_card_id=collectible_card.id,
            image_type='front',
            path=image_filename
        )
        db.session.add(card_image)

        # Create CollectibleVerification
        verification_status = random.choice(['pending', 'verified', 'rejected'])
        verification = CollectibleVerification(
            product_id=product.id,
            collectible_card_id=collectible_card.id,
            is_graded=is_graded,
            verification_status=verification_status,
            created_at=utcnow(),
            submission_count=1,
        )
        db.session.add(verification)
        db.session.flush()

        # Create verification history
        history = CardVerificationHistory(
            verification_id=verification.id,
            previous_status='pending',
            new_status=verification_status,
            change_reason='Initial submission reviewed',
            created_at=utcnow()
        )
        db.session.add(history)

        print(f"✓ Created Football card: {card_data['name']}")

def main():
    with app.app_context():
        print("\n🎴 Seeding 20 collectible trading cards...\n")

        # Get or create seller user
        seller = User.query.filter_by(username='seller').first()
        if not seller:
            print("Error: 'seller' user not found. Create a seller account first.")
            return

        # Get card types
        pokemon_type = CardType.query.filter_by(slug='pokemon').first()
        football_type = CardType.query.filter_by(slug='football').first()

        if not pokemon_type or not football_type:
            print("Error: Card types not found. Run seed_card_types.py first.")
            return

        # Seed cards
        print("📱 Creating Pokemon cards...")
        seed_pokemon_cards(seller, pokemon_type)

        print("\n⚽ Creating Football cards...")
        seed_football_cards(seller, football_type)

        # Commit all changes
        db.session.commit()
        print("\n✅ Successfully seeded 20 collectible cards!")
        print(f"   Seller: {seller.name}")
        print(f"   Login to /seller/collectibles to view your inventory")

if __name__ == '__main__':
    main()
