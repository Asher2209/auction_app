#!/usr/bin/env python
"""Download the official front scans of the demo cards (scripts/seed_collectible_cards.py) for local demos.

The scans come from the Pokemon TCG API's image host (https://pokemontcg.io). The artwork belongs to The Pokemon
Company, so the files go to scripts/demo_card_images/, which git ignores: never commit them (this repository is
public). Without them the seed uses plain placeholder images. Run this before scripts/seed.py:
    python scripts/fetch_demo_card_images.py
"""
import importlib.util
import io
import sys
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
URL = "https://images.pokemontcg.io/{set_id}/{number}_hires.png"
MAX_BYTES = 5 * 1024 * 1024  # the scans are just under 1 MB; anything far bigger is not one


def demo_cards():
    spec = importlib.util.spec_from_file_location("seed_collectible_cards", HERE / "seed_collectible_cards.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.POKEMON_CARDS, module.IMAGE_DIR


def fetch(card, dest, opener=urllib.request.urlopen):
    """Download one card's scan to dest/<api_id>.png; raise ValueError if the reply is not a PNG of sensible size."""
    set_id, number = card["api_id"].split("-")
    request = urllib.request.Request(URL.format(set_id=set_id, number=number), headers={"User-Agent": "ChainBid demo seed"})
    with opener(request, timeout=60) as reply:
        data = reply.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"{card['api_id']}: the download is larger than {MAX_BYTES // (1024 * 1024)} MB")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except Exception as e:
        raise ValueError(f"{card['api_id']}: the download is not a valid image ({e})") from e
    if fmt != "PNG":
        raise ValueError(f"{card['api_id']}: expected a PNG, got {fmt}")
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{card['api_id']}.png"
    path.write_bytes(data)
    return path


def main():
    cards, dest = demo_cards()
    failed = 0
    for card in cards:
        path = dest / f"{card['api_id']}.png"
        if path.is_file():
            print(f"  have  {path.name}")
            continue
        try:
            fetch(card, dest)
            print(f"  saved {path.name}  {card['name']}")
        except (OSError, ValueError) as e:
            failed += 1
            print(f"  FAILED {card['api_id']}: {e}")
    print(f"Card scans are in {dest} (not committed). Card images: Pokemon TCG API (pokemontcg.io); "
          "artwork (c) The Pokemon Company.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
