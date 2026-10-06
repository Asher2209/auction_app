"""Seed card types for trading cards marketplace"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db
from app.models import CardType

CARD_TYPES = [
    {
        'name': 'Pokémon',
        'slug': 'pokemon',
        'description': 'Pokémon trading cards (TCG)',
        'field_schema': {
            'pokemon_name': {'type': 'string', 'required': False},
            'hp': {'type': 'integer', 'required': False},
            'holo_type': {'type': 'string', 'required': False},
            'first_edition': {'type': 'boolean', 'required': False},
            'shadowless': {'type': 'boolean', 'required': False},
            'promo': {'type': 'boolean', 'required': False},
            'illustrator': {'type': 'string', 'required': False},
        }
    },
    {
        'name': 'Football / Soccer',
        'slug': 'football',
        'description': 'Football and soccer trading cards',
        'field_schema': {
            'player_name': {'type': 'string', 'required': False},
            'team': {'type': 'string', 'required': False},
            'national_team': {'type': 'string', 'required': False},
            'league': {'type': 'string', 'required': False},
            'season': {'type': 'string', 'required': False},
            'is_rookie': {'type': 'boolean', 'required': False},
            'is_autograph': {'type': 'boolean', 'required': False},
            'is_relic': {'type': 'boolean', 'required': False},
            'is_numbered': {'type': 'boolean', 'required': False},
            'serial_number': {'type': 'string', 'required': False},
        }
    },
    {
        'name': 'Cricket',
        'slug': 'cricket',
        'description': 'Cricket trading cards',
        'field_schema': {
            'player_name': {'type': 'string', 'required': False},
            'team': {'type': 'string', 'required': False},
            'series': {'type': 'string', 'required': False},
            'match': {'type': 'string', 'required': False},
        }
    },
    {
        'name': 'Basketball',
        'slug': 'basketball',
        'description': 'Basketball trading cards',
        'field_schema': {
            'player_name': {'type': 'string', 'required': False},
            'team': {'type': 'string', 'required': False},
            'season': {'type': 'string', 'required': False},
            'is_rookie': {'type': 'boolean', 'required': False},
        }
    },
    {
        'name': 'Trading Card Game (General)',
        'slug': 'tcg_general',
        'description': 'Other trading card games and collectibles',
        'field_schema': {
            'game_name': {'type': 'string', 'required': False},
            'expansion': {'type': 'string', 'required': False},
        }
    },
]


def main():
    app = create_app()
    with app.app_context():
        # Check if card types already exist
        if CardType.query.first():
            print("Card types already seeded, skipping.")
            return

        for card_type_data in CARD_TYPES:
            card_type = CardType(
                name=card_type_data['name'],
                slug=card_type_data['slug'],
                description=card_type_data['description'],
                is_active=True,
            )
            card_type.set_field_schema(card_type_data['field_schema'])
            db.session.add(card_type)

        db.session.commit()
        print(f"✓ Seeded {len(CARD_TYPES)} card types")
        for ct in CARD_TYPES:
            print(f"  - {ct['name']} ({ct['slug']})")


if __name__ == "__main__":
    main()
