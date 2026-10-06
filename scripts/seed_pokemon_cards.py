"""Seed trading cards with Pokémon card data using reliable image sources"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import CollectibleCard, CardType, CardImage, Product, User, Category
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import text

app = create_app()

# Pokémon cards with reliable public image URLs
POKEMON_CARDS = [
    {"name": "Charizard", "set": "Base Set", "type": "Fire", "rarity": "Holo Rare", "value": 150.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/6.png"},
    {"name": "Blastoise", "set": "Base Set", "type": "Water", "rarity": "Holo Rare", "value": 120.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/9.png"},
    {"name": "Venusaur", "set": "Base Set", "type": "Grass", "rarity": "Holo Rare", "value": 110.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/3.png"},
    {"name": "Dragonite", "set": "Base Set", "type": "Dragon", "rarity": "Holo Rare", "value": 180.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/149.png"},
    {"name": "Gyarados", "set": "Base Set", "type": "Water", "rarity": "Holo Rare", "value": 140.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/130.png"},
    {"name": "Alakazam", "set": "Base Set", "type": "Psychic", "rarity": "Holo Rare", "value": 160.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/65.png"},
    {"name": "Gengar", "set": "Base Set", "type": "Ghost", "rarity": "Holo Rare", "value": 130.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/94.png"},
    {"name": "Machamp", "set": "Base Set", "type": "Fighting", "rarity": "Holo Rare", "value": 125.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/68.png"},
    {"name": "Pikachu", "set": "Base Set", "type": "Electric", "rarity": "Holo Rare", "value": 200.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png"},
    {"name": "Mewtwo", "set": "Base Set", "type": "Psychic", "rarity": "Holo Rare", "value": 190.00, "image": "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/150.png"},
]

with app.app_context():
    print("Seeding Pokémon trading cards with reliable public images...")
    
    card_type = CardType.query.filter_by(slug='pokemon').first()
    if not card_type:
        print("ERROR: Pokémon card type not found")
        sys.exit(1)
    
    category = Category.query.filter_by(id=7).first()
    if not category:
        print("ERROR: Trading Cards category not found")
        sys.exit(1)
    
    seller = User.query.filter_by(role='seller').first()
    if not seller:
        print("ERROR: No seller found")
        sys.exit(1)
    
    print("Clearing old card data...")
    db.session.execute(text('DELETE FROM card_images'))
    db.session.execute(text('DELETE FROM collectible_cards'))
    db.session.execute(text('DELETE FROM products WHERE category_id = 7'))
    db.session.commit()
    
    for card_data in POKEMON_CARDS:
        product = Product(
            title=card_data['name'],
            description=f"{card_data['name']} from {card_data['set']} set\nType: {card_data['type']}\nRarity: {card_data['rarity']}",
            seller_id=seller.id,
            category_id=7,
            approval_status='approved',
            auction_start=datetime.utcnow(),
            auction_end=datetime.utcnow() + timedelta(days=7),
            starting_price=Decimal(str(card_data['value']))
        )
        db.session.add(product)
        db.session.flush()
        
        card = CollectibleCard(
            product_id=product.id,
            card_type_id=card_type.id,
            card_name=card_data['name'],
            manufacturer='The Pokémon Company',
            set_name=card_data['set'],
            release_year=1999,
            rarity=card_data['rarity'],
            condition='Mint',
            estimated_value=Decimal(str(card_data['value']))
        )
        db.session.add(card)
        db.session.flush()
        
        image = CardImage(
            collectible_card_id=card.id,
            image_type='front',
            url=card_data['image']
        )
        db.session.add(image)
        print(f"  Added: {card_data['name']} (${card_data['value']})")
    
    db.session.commit()
    print(f"\nSuccessfully seeded {len(POKEMON_CARDS)} Pokémon cards with PokeAPI official artwork!")

