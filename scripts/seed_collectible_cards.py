#!/usr/bin/env python
"""Seed demo trading cards for local development: 5 Pokemon and 5 football cards for one seller.

Cards are created the way the seller's "Add a card" form creates them: in the "Trading Cards" category, with a
platform card ID (CARD-xxxxxx), a placeholder front image and a verification record that is PENDING. Nothing is
marked verified here: an administrator verifies each card through the checklist, as for any real submission.
Running it again skips cards the seller already has.

Run scripts/seed.py and scripts/seed_card_types.py first, then:
    python scripts/seed_collectible_cards.py [seller-email]
"""
import random
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

POKEMON_CARDS = [
    {"name": "Charizard Base Set", "hp": 120, "holo": "holographic", "set": "Base Set", "number": "4/102", "year": 1999, "first": True},
    {"name": "Blastoise Base Set", "hp": 100, "holo": "holographic", "set": "Base Set", "number": "2/102", "year": 1999, "first": True},
    {"name": "Venusaur Base Set", "hp": 100, "holo": "holographic", "set": "Base Set", "number": "15/102", "year": 1999, "first": False},
    {"name": "Mewtwo Base Set", "hp": 60, "holo": "holographic", "set": "Base Set", "number": "10/102", "year": 1999, "first": True},
    {"name": "Gyarados Base Set", "hp": 100, "holo": "holographic", "set": "Base Set", "number": "6/102", "year": 1999, "first": False},
]
FOOTBALL_CARDS = [
    {"name": "Lionel Messi Ligue 1", "player": "Lionel Messi", "team": "Paris Saint-Germain", "league": "Ligue 1", "year": 2022, "rookie": False},
    {"name": "Cristiano Ronaldo Manchester United", "player": "Cristiano Ronaldo", "team": "Manchester United", "league": "Premier League", "year": 2003, "rookie": True},
    {"name": "Mohamed Salah Liverpool", "player": "Mohamed Salah", "team": "Liverpool", "league": "Premier League", "year": 2017, "rookie": False},
    {"name": "Kylian Mbappe PSG Rookie", "player": "Kylian Mbappe", "team": "Paris Saint-Germain", "league": "Ligue 1", "year": 2017, "rookie": True},
    {"name": "Robert Lewandowski Bayern Munich", "player": "Robert Lewandowski", "team": "Bayern Munich", "league": "Bundesliga", "year": 2010, "rookie": False},
]
CONDITIONS = ["Good", "Very Good", "Excellent", "Near Mint", "Mint"]
GRADERS = ["PSA", "BGS", "CGC"]
GRADES = ["7", "8", "8.5", "9", "9.5", "10"]


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


def card_category():
    category = Category.query.filter_by(name=CARD_CATEGORY_NAME).first()
    if category is None:
        category = Category(name=CARD_CATEGORY_NAME)
        db.session.add(category)
        db.session.flush()
    return category


def add_card(app, seller, card_type, category, fields, details, colour, rng):
    """One card, as the seller form makes it. Returns the CollectibleCard, or None if the seller already has it."""
    exists = (CollectibleCard.query.join(Product).filter(Product.seller_id == seller.id,
                                                         CollectibleCard.card_name == fields["card_name"]).first())
    if exists:
        return None
    image = placeholder_image(app.config["UPLOAD_FOLDER"], fields["card_name"], colour)
    graded = rng.random() < 0.3
    product = Product(seller_id=seller.id, category_id=category.id, title=fields["card_name"],
                      description=f"Demo card. {fields['card_name']}, {fields['condition']} condition.",
                      starting_price=Decimal(rng.randint(500, 20000)), auction_start=utcnow(), auction_end=utcnow(),
                      approval_status="pending", images=[ProductImage(path=image)])
    db.session.add(product)
    db.session.flush()
    card = CollectibleCard(product_id=product.id, card_type_id=card_type.id, language="English", is_graded=graded,
                           grading_company=rng.choice(GRADERS) if graded else None,
                           grade=rng.choice(GRADES) if graded else None,
                           certification_number=str(rng.randint(10000000, 99999999)) if graded else None,
                           **fields)
    card.set_type_details(details)
    db.session.add(card)
    db.session.flush()
    assign_platform_card_id(card)  # CARD-xxxxxx, as for a real submission (this commits)
    db.session.add(CardImage(collectible_card_id=card.id, image_type="front", path=image))
    verification = CollectibleVerification(product_id=product.id, collectible_card_id=card.id,
                                           collectible_type="trading_card", is_graded=graded,
                                           verification_status="pending", submission_count=1)
    db.session.add(verification)
    db.session.flush()
    db.session.add(CardVerificationHistory(verification_id=verification.id, previous_status=None,
                                           new_status="pending", change_reason="Demo card submitted for review"))
    db.session.commit()
    return card


def seed(app, seller_email=None, rng=None):
    """Seed the demo cards inside an app context. Returns the list of created cards; raises SystemExit on a setup problem."""
    rng = rng or random.Random()
    if seller_email:
        seller = User.query.filter_by(email=seller_email, role="seller").first()
    else:
        seller = User.query.filter_by(role="seller", is_active_user=True).order_by(User.id).first()
    if seller is None:
        raise SystemExit("No seller account found. Run scripts/seed.py first, or pass a seller's email.")
    pokemon, football = (CardType.query.filter_by(slug=s).first() for s in ("pokemon", "football"))
    if pokemon is None or football is None:
        raise SystemExit("Card types are missing. Run scripts/seed_card_types.py first.")
    category = card_category()

    created = []
    for c in POKEMON_CARDS:
        fields = {"card_name": c["name"], "manufacturer": "The Pokemon Company", "set_name": c["set"], "set_code": "BS",
                  "release_year": c["year"], "card_number": c["number"], "rarity": "Holo Rare",
                  "edition": "1st Edition" if c["first"] else "Unlimited", "condition": rng.choice(CONDITIONS),
                  "condition_notes": "Demo card: see the image for details.", "country": "USA"}
        details = {"pokemon_name": c["name"].split()[0], "hp": c["hp"], "holo_type": c["holo"],
                   "first_edition": c["first"], "shadowless": False, "promo": False, "illustrator": "Ken Sugimori"}
        created.append(add_card(app, seller, pokemon, category, fields, details, (235, 200, 140), rng))
    for c in FOOTBALL_CARDS:
        fields = {"card_name": c["name"], "manufacturer": rng.choice(["Panini", "Topps"]),
                  "set_name": f"{c['league']} {c['year']}", "release_year": c["year"],
                  "card_number": str(rng.randint(1, 300)), "rarity": "Base", "condition": rng.choice(CONDITIONS),
                  "condition_notes": "Demo card: see the image for details.", "country": "UK"}
        details = {"player_name": c["player"], "team": c["team"], "league": c["league"], "season": str(c["year"]),
                   "is_rookie": c["rookie"], "is_autograph": False}
        created.append(add_card(app, seller, football, category, fields, details, (170, 190, 215), rng))
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
