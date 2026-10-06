import requests
from typing import Optional, Dict, List

class PokemonTCGService:
    BASE_URL = "https://api.pokemontcg.io/v2"
    
    @staticmethod
    def get_cards(limit: int = 20, q: str = "") -> Optional[Dict]:
        """Fetch cards from Pokémon TCG API"""
        try:
            url = f"{PokemonTCGService.BASE_URL}/cards"
            params = {"pageSize": min(limit, 250)}
            if q:
                params["q"] = q
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching from Pokémon TCG API: {e}")
            return None
    
    @staticmethod
    def get_popular_cards(limit: int = 10) -> List[Dict]:
        """Fetch popular Pokémon cards without complex queries"""
        try:
            data = PokemonTCGService.get_cards(limit=limit * 5)
            if not data or "data" not in data:
                return []
            
            cards = []
            for card in data["data"][:limit * 3]:
                if card.get("images", {}).get("large") and len(cards) < limit:
                    card_type = card.get("types", ["Normal"])[0] if card.get("types") else "Normal"
                    cards.append({
                        "id": card.get("id"),
                        "name": card.get("name"),
                        "type": card_type,
                        "set": card.get("set", {}).get("name", "Unknown Set"),
                        "number": card.get("number"),
                        "rarity": card.get("rarity", "Common"),
                        "image_url": card.get("images", {}).get("large"),
                        "condition": "Mint",
                        "estimated_value": 35 + (len(cards) * 12),
                    })
            
            return cards
        except Exception as e:
            print(f"Error processing cards: {e}")
            return []
