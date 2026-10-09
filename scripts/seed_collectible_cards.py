#!/usr/bin/env python
"""Seed demo trading cards for local development: the 10 holo rares of the 1999 Pokemon Base Set, for one seller.

Cards are created the way the seller's "Add a card" form creates them: in the "Trading Cards" category, with a
platform card ID (CARD-xxxxxx), a front image and a verification record that is PENDING. Nothing is marked
verified here: an administrator verifies each card through the checklist, as for any real submission.
Running it again skips cards the seller already has.

The front image is the official card scan when scripts/fetch_demo_card_images.py has downloaded it into
scripts/demo_card_images/ (git ignores that folder; the artwork belongs to The Pokemon Company), and a plain
placeholder otherwise. The cards are ungraded: no grading certificate number is made up.

Run scripts/seed.py and scripts/seed_card_types.py first, then:
    python scripts/seed_collectible_cards.py [seller-email]
"""
import random
import shutil
import sys
import uuid
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.blueprints.seller.routes_cards import CARD_CATEGORY_NAME  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (CardImage, CardType, CardVerificationHistory, Category, CollectibleCard,  # noqa: E402
                        CollectibleVerification, Product, ProductImage, User, utcnow)
from app.services.card_identity_service import assign_platform_card_id  # noqa: E402

# The holo rares of the 1999 English Base Set (Wizards of the Coast), as the Pokemon TCG API lists them (set "base1").
POKEMON_CARDS = [
    {"api_id": "base1-1", "name": "Alakazam", "number": "1/102", "hp": 80, "illustrator": "Ken Sugimori"},
    {"api_id": "base1-2", "name": "Blastoise", "number": "2/102", "hp": 100, "illustrator": "Ken Sugimori"},
    {"api_id": "base1-3", "name": "Chansey", "number": "3/102", "hp": 120, "illustrator": "Ken Sugimori"},
    {"api_id": "base1-4", "name": "Charizard", "number": "4/102", "hp": 120, "illustrator": "Mitsuhiro Arita"},
    {"api_id": "base1-6", "name": "Gyarados", "number": "6/102", "hp": 100, "illustrator": "Mitsuhiro Arita"},
    {"api_id": "base1-10", "name": "Mewtwo", "number": "10/102", "hp": 60, "illustrator": "Ken Sugimori"},
    {"api_id": "base1-12", "name": "Ninetales", "number": "12/102", "hp": 80, "illustrator": "Ken Sugimori"},
    {"api_id": "base1-14", "name": "Raichu", "number": "14/102", "hp": 80, "illustrator": "Ken Sugimori"},
    {"api_id": "base1-15", "name": "Venusaur", "number": "15/102", "hp": 100, "illustrator": "Mitsuhiro Arita"},
    {"api_id": "base1-16", "name": "Zapdos", "number": "16/102", "hp": 90, "illustrator": "Ken Sugimori"},
]
IMAGE_DIR = Path(__file__).resolve().parent / "demo_card_images"  # filled by fetch_demo_card_images.py, ignored by git
CONDITIONS = ["Good", "Very Good", "Excellent", "Near Mint", "Mint"]


def placeholder_image(upload_folder, card_name, colour):
    """A plain 400x600 PNG with the card's name, saved under the upload folder. Returns its file name."""
    img = Image.new("RGB", (400, 600), colour)
    draw = ImageDraw.Draw(img)
    draw.rectangle([5, 5, 394, 594], outline=(40, 40, 40), width=3)
    draw.text((200, 280), card_name[:24], fill=(30, 30, 30), anchor="mm")
    draw.text((200, 320), "DEMO IMAGE", fill=(30, 30, 30), anchor="mm")
    Path(upload_folder).mkdir(parents=True, exist_ok=True)
    name = f"seed_{uuid.uuid4().hex}.png"
    img.save(Path(upload_folder) / name, "PNG")
    return name


def scan_image(upload_folder, scan):
    """Copy a downloaded card scan into the upload folder under a random name. Returns its file name."""
    Path(upload_folder).mkdir(parents=True, exist_ok=True)
    name = f"seed_{uuid.uuid4().hex}.png"
    shutil.copyfile(scan, Path(upload_folder) / name)
    return name


def card_category():
    category = Category.query.filter_by(name=CARD_CATEGORY_NAME).first()
    if category is None:
        category = Category(name=CARD_CATEGORY_NAME)
        db.session.add(category)
        db.session.flush()
    return category


def add_card(app, seller, card_type, category, fields, details, colour, rng, scan=None):
    """One card, as the seller form makes it. Returns the CollectibleCard, or None if the seller already has it."""
    exists = (CollectibleCard.query.join(Product).filter(Product.seller_id == seller.id,
                                                         CollectibleCard.card_name == fields["card_name"]).first())
    if exists:
        return None
    if scan is not None and scan.is_file():
        image = scan_image(app.config["UPLOAD_FOLDER"], scan)
    else:
        image = placeholder_image(app.config["UPLOAD_FOLDER"], fields["card_name"], colour)
    product = Product(seller_id=seller.id, category_id=category.id, title=fields["card_name"],
                      description=f"Demo card. {fields['card_name']} {fields['card_number']} ({fields['release_year']}), {fields['condition']} condition.",
                      starting_price=Decimal(rng.randint(500, 20000)), auction_start=utcnow(), auction_end=utcnow(),
                      approval_status="pending", images=[ProductImage(path=image)])
    db.session.add(product)
    db.session.flush()
    card = CollectibleCard(product_id=product.id, card_type_id=card_type.id, language="English", is_graded=False,
                           **fields)
    card.set_type_details(details)
    db.session.add(card)
    db.session.flush()
    assign_platform_card_id(card)  # CARD-xxxxxx, as for a real submission (this commits)
    db.session.add(CardImage(collectible_card_id=card.id, image_type="front", path=image))
    verification = CollectibleVerification(product_id=product.id, collectible_card_id=card.id,
                                           collectible_type="trading_card", is_graded=False,
                                           verification_status="pending", submission_count=1)
    db.session.add(verification)
    db.session.flush()
    db.session.add(CardVerificationHistory(verification_id=verification.id, previous_status=None,
                                           new_status="pending", change_reason="Demo card submitted for review"))
    db.session.commit()
    return card


def seed(app, seller_email=None, rng=None, image_dir=IMAGE_DIR):
    """Seed the demo cards inside an app context. Returns the list of created cards; raises SystemExit on a setup problem."""
    rng = rng or random.Random()
    if seller_email:
        seller = User.query.filter_by(email=seller_email, role="seller").first()
    else:
        seller = User.query.filter_by(role="seller", is_active_user=True).order_by(User.id).first()
    if seller is None:
        raise SystemExit("No seller account found. Run scripts/seed.py first, or pass a seller's email.")
    pokemon = CardType.query.filter_by(slug="pokemon").first()
    if pokemon is None:
        raise SystemExit("Card types are missing. Run scripts/seed_card_types.py first.")
    category = card_category()

    created = []
    for c in POKEMON_CARDS:
        condition = rng.choice(CONDITIONS)
        fields = {"card_name": f"{c['name']} Base Set", "manufacturer": "Wizards of the Coast", "set_name": "Base Set",
                  "set_code": "BS", "release_year": 1999, "card_number": c["number"], "rarity": "Rare Holo",
                  "edition": "Unlimited", "condition": condition,
                  "condition_notes": "Demo card: the image is the official card scan, not a photo of this copy.",
                  "country": "USA"}
        details = {"pokemon_name": c["name"], "hp": c["hp"], "holo_type": "Holo", "first_edition": False,
                   "shadowless": False, "promo": False, "illustrator": c["illustrator"]}
        scan = Path(image_dir) / f"{c['api_id']}.png" if image_dir else None
        created.append(add_card(app, seller, pokemon, category, fields, details, (235, 200, 140), rng, scan))
    return seller, [c for c in created if c is not None]


def main():
    app = create_app()
    with app.app_context():
        seller, created = seed(app, sys.argv[1] if len(sys.argv) > 1 else None)
        print(f"Seeded {len(created)} demo cards for {seller.email} (pending verification).")
        for card in created:
            print(f"  {card.platform_card_id}  {card.card_name}")


if __name__ == "__main__":
    main()
