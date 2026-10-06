#!/usr/bin/env python
import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import random

sys.path.insert(0, str(Path(__file__).parent.parent))

def create_pokemon_card_image(card_name, rarity='Common'):
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
    
    pokemon_colors = [(255, 100, 50), (50, 150, 255), (100, 200, 50)]
    card_image_area_color = random.choice(pokemon_colors)
    draw.rectangle([15, 15, width-15, int(height*0.4)], fill=card_image_area_color, outline=(50, 50, 50), width=2)
    
    try:
        font_path = r"C:\Windows\Fonts\arial.ttf"
        title_font = ImageFont.truetype(font_path, 18)
        text_font = ImageFont.truetype(font_path, 12)
        small_font = ImageFont.truetype(font_path, 10)
    except:
        title_font = text_font = small_font = ImageFont.load_default()
    
    draw.text((25, int(height*0.42)), "POKEMON", fill=(100, 100, 100), font=text_font)
    draw.text((25, int(height*0.50)), card_name[:20], fill=(0, 0, 0), font=title_font)
    draw.text((25, int(height*0.62)), f"Rarity: {rarity}", fill=(50, 50, 50), font=small_font)
    draw.text((25, height-40), "Base Set | 1999", fill=(100, 100, 100), font=small_font)
    
    return img

def create_football_card_image(player_name, team='PSG'):
    width, height = 300, 420
    img = Image.new('RGB', (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    
    team_colors = {'PSG': (0, 85, 204), 'Manchester United': (220, 20, 20), 'Liverpool': (200, 16, 16)}
    accent_color = team_colors.get(team, (0, 85, 204))
    
    draw.rectangle([2, 2, width-2, height-2], outline=accent_color, width=4)
    
    try:
        font_path = r"C:\Windows\Fonts\arial.ttf"
        title_font = ImageFont.truetype(font_path, 18)
        text_font = ImageFont.truetype(font_path, 12)
        small_font = ImageFont.truetype(font_path, 10)
    except:
        title_font = text_font = small_font = ImageFont.load_default()
    
    draw.text((25, int(height*0.42)), "FOOTBALL", fill=(100, 100, 100), font=text_font)
    draw.text((25, int(height*0.50)), player_name[:20], fill=(0, 0, 0), font=title_font)
    draw.text((25, int(height*0.62)), f"Team: {team}", fill=(50, 50, 50), font=small_font)
    draw.text((25, height-40), "Premium Card", fill=(100, 100, 100), font=small_font)
    
    return img

uploads_dir = Path('app/static/uploads')
uploads_dir.mkdir(parents=True, exist_ok=True)

print("\n[IMAGES] Generating card images...\n")

# Pokemon cards
pokemon_names = ["Charizard 1", "Charizard 2", "Charizard 3", "Charizard 4", "Charizard 5"]
for i, name in enumerate(pokemon_names, 1):
    img = create_pokemon_card_image(name, rarity=['Common', 'Uncommon', 'Rare', 'Holo Rare'][i % 4])
    filename = f"card_poke_{i}.png"
    img.save(uploads_dir / filename, 'PNG')
    print(f"  OK {name} -> {filename}")

# Football cards
football_names = ["Messi Card 1", "Ronaldo Card 1", "Salah Card 1", "Mbappe Card 1", "Lewandowski Card 1"]
for i, name in enumerate(football_names, 1):
    img = create_football_card_image(name, team=['PSG', 'Manchester United', 'Liverpool', 'PSG', 'Bayern Munich'][i-1])
    filename = f"card_foot_{i}.png"
    img.save(uploads_dir / filename, 'PNG')
    print(f"  OK {name} -> {filename}")

print("\n[SUCCESS] Card images generated!\n")
