#!/usr/bin/env python
"""Generate high-quality card images with details"""
import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import random

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ['FLASK_APP'] = 'app'

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from app.models import CollectibleCard, CardImage

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///auction.db'
db = SQLAlchemy(app)

POKEMON_COLORS = {
    'fire': (255, 100, 50),
    'water': (50, 150, 255),
    'grass': (100, 200, 50),
}

def create_pokemon_card_image(card_name, rarity='Common'):
    """Create a Pokemon-style card image"""
    width, height = 300, 420
    img = Image.new('RGB', (width, height), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    
    rarity_colors = {
        'Common': (180, 180, 180),
        'Uncommon': (100, 150, 100),
        'Rare': (200, 150, 50),
        'Holo Rare': (255, 200, 0),
    }
    accent_color = rarity_colors.get(rarity, (180, 180, 180))
    
    draw.rectangle([2, 2, width-2, height-2], outline=accent_color, width=3)
    draw.rectangle([8, 8, width-8, height-8], outline=(100, 100, 100), width=1)
    
    card_image_area_color = random.choice(list(POKEMON_COLORS.values()))
    draw.rectangle([15, 15, width-15, int(height*0.4)], fill=card_image_area_color, outline=(50, 50, 50), width=2)
    
    try:
        title_font = ImageFont.truetype("C:\Windows\Fonts\arial.ttf", 18)
        text_font = ImageFont.truetype("C:\Windows\Fonts\arial.ttf", 12)
        small_font = ImageFont.truetype("C:\Windows\Fonts\arial.ttf", 10)
    except:
        title_font = text_font = small_font = ImageFont.load_default()
    
    draw.text((25, int(height*0.42)), "POKEMON", fill=(100, 100, 100), font=text_font)
    draw.text((25, int(height*0.50)), card_name[:20], fill=(0, 0, 0), font=title_font)
    
    y_pos = int(height*0.62)
    draw.text((25, y_pos), f"Rarity: {rarity}", fill=(50, 50, 50), font=small_font)
    draw.text((25, y_pos+25), "HP: 120", fill=(200, 0, 0), font=small_font)
    draw.text((25, height-40), "Base Set | 1999", fill=(100, 100, 100), font=small_font)
    
    return img

def create_football_card_image(player_name, team='PSG'):
    """Create a football-style card image"""
    width, height = 300, 420
    img = Image.new('RGB', (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    
    team_colors = {
        'PSG': (0, 85, 204),
        'Manchester United': (220, 20, 20),
        'Liverpool': (200, 16, 16),
        'Bayern Munich': (220, 20, 20),
    }
    accent_color = team_colors.get(team, (0, 85, 204))
    
    draw.rectangle([2, 2, width-2, height-2], outline=accent_color, width=4)
    
    try:
        title_font = ImageFont.truetype("C:\Windows\Fonts\arial.ttf", 18)
        text_font = ImageFont.truetype("C:\Windows\Fonts\arial.ttf", 12)
        small_font = ImageFont.truetype("C:\Windows\Fonts\arial.ttf", 10)
    except:
        title_font = text_font = small_font = ImageFont.load_default()
    
    draw.text((25, int(height*0.42)), "FOOTBALL / SOCCER", fill=(100, 100, 100), font=text_font)
    draw.text((25, int(height*0.50)), player_name[:20], fill=(0, 0, 0), font=title_font)
    
    y_pos = int(height*0.62)
    draw.text((25, y_pos), f"Team: {team}", fill=(50, 50, 50), font=small_font)
    draw.text((25, height-40), "Premium Edition", fill=(100, 100, 100), font=small_font)
    
    return img

def update_card_images():
    """Update all card images with better graphics"""
    with app.app_context():
        cards = CollectibleCard.query.all()
        uploads_dir = Path('app/static/uploads')
        uploads_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n[IMAGES] Updating {len(cards)} card images...\n")
        
        for card in cards:
            try:
                if 'pokemon' in card.card_type.slug.lower():
                    img = create_pokemon_card_image(card.card_name, rarity=card.rarity)
                    card_type = 'pokemon'
                else:
                    img = create_football_card_image(card.card_name, team=card.set_name)
                    card_type = 'football'
                
                filename = f"card_{card.id}_main.png"
                filepath = uploads_dir / filename
                img.save(filepath, 'PNG')
                
                image_record = CardImage.query.filter_by(
                    collectible_card_id=card.id, image_type='front').first()
                
                if image_record:
                    image_record.path = filename
                else:
                    image_record = CardImage(
                        collectible_card_id=card.id, image_type='front', path=filename)
                    db.session.add(image_record)
                
                db.session.commit()
                print(f"  OK {card.card_name}")
            except Exception as e:
                print(f"  ERROR {card.card_name}: {e}")
                db.session.rollback()
        
        print(f"\n[SUCCESS] Updated card images!")

if __name__ == '__main__':
    update_card_images()
