#!/usr/bin/env python
"""
Simple seed script for collectible cards that works without full app import
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw
import random
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Flask app minimal way
os.environ['FLASK_APP'] = 'app'

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Create minimal Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///auction.db'
db = SQLAlchemy(app)

# Import models after db is set up
from app.models import (
    User, Product, CollectibleCard, CardType, CardImage,
    CardVerificationHistory, CollectibleVerification, utcnow
)
from app.models import ProductImage

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
    {'name': 'Kylian Mbappe PSG Rookie', 'player': 'Kylian Mbappe', 'team': 'Paris Saint-Germain', 'league': 'Ligue 1', 'year': 2017, 'is_rookie': True},
    {'name': 'Robert Lewandowski Bayern Munich', 'player': 'Robert Lewandowski', 'team': 'Bayern Munich', 'league': 'Bundesliga', 'year': 2010, 'is_rookie': False},
]

CONDITIONS = ['Poor', 'Fair', 'Good', 'Very Good', 'Excellent', 'Near Mint', 'Mint']
GRADING_COMPANIES = ['PSA', 'Beckett', 'CGC', None]
GRADES = ['1.0', '2.5', '4.5', '6.5', '7.5', '8.5', '9.0', '9.5', '10.0']

def create_placeholder_image(card_name, card_type='pokemon'):
    """Create a simple placeholder card image"""
    width, height = 400, 600

    if card_type == 'pokemon':
        bg_color = (255, 200, 100)
        accent_color = (255, 150, 0)
    else:
        bg_color = (100, 150, 200)
        accent_color = (50, 100, 200)

    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Draw border
    draw.rectangle([5, 5, width-5, height-5], outline=accent_color, width=3)

    # Draw center text
    text_y = height // 2 - 40
    for line in [card_name[:20], card_name[20:40] if len(card_name) > 20 else '']:
        if line:
            draw.text((width//2, text_y), line, fill=(50, 50, 50), anchor='mm')
            text_y += 50

    draw.text((width//2, height - 50), card_type.upper(), fill=(255, 255, 255), anchor='mm')

    return img

def save_card_image(card_name, card_type='pokemon'):
    """Save placeholder image and return filename"""
    img = create_placeholder_image(card_name, card_type)

    uploads_dir = Path('app/static/uploads')
    uploads_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    filename = f'card_{timestamp}.png'
    filepath = uploads_dir / filename

    img.save(filepath, 'PNG')
    return filename

def main():
    with app.app_context():
        print("\n[CARD] Seeding 20 collectible trading cards...\n")

        # Get seller user (find first user with seller role)
        seller = db.session.query(User).filter_by(role='seller').first()
        if not seller:
            print("[ERROR] No seller user found. Create a seller account first.")
            return

        # Get card types
        pokemon_type = db.session.query(CardType).filter_by(slug='pokemon').first()
        football_type = db.session.query(CardType).filter_by(slug='football').first()

        if not pokemon_type or not football_type:
            print("[ERROR] Card types not found. Run seed_card_types.py first.")
            return

        # Get or create trading cards category
        from app.models import Category
        category = db.session.query(Category).filter_by(name='Trading Cards').first()
        if not category:
            category = db.session.query(Category).first()
        if not category:
            print("[ERROR] No category found. Create a category first.")
            return

        print("[POKEMON] Creating Pokemon cards...")
        conditions = random.sample(CONDITIONS, len(POKEMON_CARDS))

        for idx, card_data in enumerate(POKEMON_CARDS):
            image_filename = save_card_image(card_data['name'], 'pokemon')

            product = Product(
                seller_id=seller.id,
                category_id=category.id,
                title=card_data['name'],
                description=f"Collectible Pokemon card from {card_data['set']} set. {card_data['name']} in {conditions[idx]} condition.",
                starting_price=random.randint(100, 5000) / 100,
                auction_start=utcnow(),
                auction_end=utcnow(),
                approval_status='pending',
            )
            db.session.add(product)
            db.session.flush()

            product_image = ProductImage(product_id=product.id, path=image_filename)
            db.session.add(product_image)

            is_graded = random.choice([True, False, False, False])

            collectible_card = CollectibleCard(
                product_id=product.id,
                card_type_id=pokemon_type.id,
                card_name=card_data['name'],
                manufacturer='The Pokemon Company',
                set_name=card_data['set'],
                set_code='BS',
                release_year=card_data['year'],
                card_number=card_data['number'],
                rarity=random.choice(['Common', 'Uncommon', 'Rare', 'Holo Rare']),
                condition=conditions[idx],
                condition_notes=f"Well-preserved card with {conditions[idx]} condition.",
                language='English',
                country='USA',
                is_graded=is_graded,
                grading_company=random.choice(GRADING_COMPANIES) if is_graded else None,
                grade=random.choice(GRADES) if is_graded else None,
                certification_number=f"PSA-{random.randint(100000, 999999)}" if is_graded else None,
                estimated_value=random.randint(50, 10000) / 100,
                type_details=json.dumps({
                    'pokemon_name': card_data['name'].split()[0],
                    'pokemon_hp': card_data['hp'],
                    'pokemon_holo_type': card_data['holo'],
                    'pokemon_first_edition': card_data['is_first'],
                    'pokemon_shadowless': False,
                    'pokemon_promo': False,
                    'pokemon_illustrator': 'Ken Sugimori',
                })
            )
            db.session.add(collectible_card)
            db.session.flush()

            card_image = CardImage(
                collectible_card_id=collectible_card.id,
                image_type='front',
                path=image_filename
            )
            db.session.add(card_image)

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

            history = CardVerificationHistory(
                verification_id=verification.id,
                previous_status='pending',
                new_status=verification_status,
                change_reason='Initial submission',
                created_at=utcnow()
            )
            db.session.add(history)

            print(f"  OK {card_data['name']}")

        print("\n[FOOTBALL] Creating Football cards...")
        conditions = random.sample(CONDITIONS, len(FOOTBALL_CARDS))

        for idx, card_data in enumerate(FOOTBALL_CARDS):
            image_filename = save_card_image(card_data['name'], 'football')

            product = Product(
                seller_id=seller.id,
                category_id=category.id,
                title=card_data['name'],
                description=f"Collectible football card of {card_data['player']} from {card_data['team']}. {conditions[idx]} condition.",
                starting_price=random.randint(50, 2000) / 100,
                auction_start=utcnow(),
                auction_end=utcnow(),
                approval_status='pending',
            )
            db.session.add(product)
            db.session.flush()

            product_image = ProductImage(product_id=product.id, path=image_filename)
            db.session.add(product_image)

            is_graded = random.choice([True, False, False])

            collectible_card = CollectibleCard(
                product_id=product.id,
                card_type_id=football_type.id,
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
                grading_company=random.choice(GRADING_COMPANIES) if is_graded else None,
                grade=random.choice(GRADES) if is_graded else None,
                certification_number=f"BVG-{random.randint(100000, 999999)}" if is_graded else None,
                estimated_value=random.randint(25, 5000) / 100,
                type_details=json.dumps({
                    'football_player_name': card_data['player'],
                    'football_team': card_data['team'],
                    'football_league': card_data['league'],
                    'football_season': str(card_data['year']),
                    'football_is_rookie': card_data['is_rookie'],
                    'football_is_autograph': False,
                })
            )
            db.session.add(collectible_card)
            db.session.flush()

            card_image = CardImage(
                collectible_card_id=collectible_card.id,
                image_type='front',
                path=image_filename
            )
            db.session.add(card_image)

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

            history = CardVerificationHistory(
                verification_id=verification.id,
                previous_status='pending',
                new_status=verification_status,
                change_reason='Initial submission reviewed',
                created_at=utcnow()
            )
            db.session.add(history)

            print(f"  OK {card_data['name']}")

        # Commit all changes
        db.session.commit()
        print("\n[SUCCESS] Seeded 20 collectible cards!")
        print(f"          Visit: /seller/collectibles to view inventory")

if __name__ == '__main__':
    main()
