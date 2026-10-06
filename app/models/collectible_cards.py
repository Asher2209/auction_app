import json
from datetime import datetime
from ..extensions import db
from . import utcnow


class CardType(db.Model):
    """Registry of supported collectible card types (Pokémon, Football, Cricket, etc.)"""
    __tablename__ = 'card_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)  # "Pokémon", "Football/Soccer", etc.
    slug = db.Column(db.String(100), nullable=False, unique=True)  # "pokemon", "football", etc.
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)

    # JSON schema defining type-specific fields
    # Example: {"pokemon_name": {"type": "string", "required": true}, ...}
    field_schema = db.Column(db.Text)  # JSON

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    collectible_cards = db.relationship('CollectibleCard', backref='card_type', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<CardType {self.name}>'

    def get_field_schema(self):
        """Parse JSON field schema"""
        if self.field_schema:
            return json.loads(self.field_schema)
        return {}

    def set_field_schema(self, schema_dict):
        """Store field schema as JSON"""
        self.field_schema = json.dumps(schema_dict)


class CollectibleCard(db.Model):
    """Core trading card metadata - extends products with card-specific fields"""
    __tablename__ = 'collectible_cards'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), unique=True, nullable=False)
    card_type_id = db.Column(db.Integer, db.ForeignKey('card_types.id'), nullable=False)

    # Common card fields
    card_name = db.Column(db.String(255), nullable=False)  # e.g., "Charizard", "Lionel Messi"
    manufacturer = db.Column(db.String(100))  # e.g., "The Pokémon Company", "Panini"
    set_name = db.Column(db.String(100))  # e.g., "Base Set", "2022 FIFA World Cup"
    set_code = db.Column(db.String(50))  # e.g., "BS", "WC22"
    release_year = db.Column(db.Integer)
    card_number = db.Column(db.String(50))  # e.g., "4/102"
    rarity = db.Column(db.String(50))  # e.g., "Rare Holo", "Common", "Ultra Rare"

    # Condition assessment
    condition = db.Column(db.String(50), nullable=False)  # Poor, Played, Good, Very Good, Excellent, Near Mint, Mint
    condition_notes = db.Column(db.Text)  # Seller's detailed condition description

    # Additional metadata
    language = db.Column(db.String(50), default='English')  # "English", "Japanese", etc.
    country = db.Column(db.String(50))  # "USA", "Japan", etc.
    edition = db.Column(db.String(100))  # "First Edition", "Unlimited", etc.

    # Grading information (optional - for graded cards)
    is_graded = db.Column(db.Boolean, default=False)
    grading_company = db.Column(db.String(100))  # "PSA", "Beckett", "CGC", etc.
    grade = db.Column(db.String(20))  # "PSA 9", "Gem Mint 10", etc.
    certification_number = db.Column(db.String(100))  # Grader's cert number
    certification_url = db.Column(db.String(500))  # Link to grader's certificate page

    # Seller-provided estimated value (before verification)
    estimated_value = db.Column(db.Numeric(12, 2))

    # Type-specific details stored as JSON
    # For Pokémon: {"pokemon_name": "Charizard", "hp": 120, "holo_type": "Holo", ...}
    # For Football: {"player_name": "Messi", "team": "PSG", "rookie": false, ...}
    type_details = db.Column(db.Text)  # JSON

    # Audit trail
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    product = db.relationship('Product', backref=db.backref('collectible_card', uselist=False))

    def __repr__(self):
        return f'<CollectibleCard {self.card_name} - {self.set_name}>'

    def get_type_details(self):
        """Parse JSON type-specific details"""
        if self.type_details:
            return json.loads(self.type_details)
        return {}

    def set_type_details(self, details_dict):
        """Store type-specific details as JSON"""
        self.type_details = json.dumps(details_dict)


class CardImage(db.Model):
    """Specialized images for collectible cards (front, back, grading slab, etc.)"""
    __tablename__ = 'card_images'

    id = db.Column(db.Integer, primary_key=True)
    collectible_card_id = db.Column(db.Integer, db.ForeignKey('collectible_cards.id'), nullable=False)

    # Image type identifies what the image shows
    image_type = db.Column(db.String(50), nullable=False)  # "front", "back", "slab", "certificate", "close_up"
    path = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=utcnow)

    collectible_card = db.relationship('CollectibleCard', backref=db.backref('images', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<CardImage {self.image_type} - {self.path}>'


class CardVerificationChecklist(db.Model):
    """Checklist items verified by admin during card verification"""
    __tablename__ = 'card_verification_checklists'

    id = db.Column(db.Integer, primary_key=True)
    verification_id = db.Column(db.Integer, db.ForeignKey('collectible_verifications.id'), nullable=False)

    check_type = db.Column(db.String(100), nullable=False)  # e.g., "card_identity", "set_checked", "condition_reviewed"
    result = db.Column(db.String(20), default='pending')  # "verified", "needs_review", "failed"
    notes = db.Column(db.Text)  # Admin notes for this specific check

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self):
        return f'<CardVerificationChecklist {self.check_type}: {self.result}>'


class CardVerificationHistory(db.Model):
    """Audit trail of verification status changes"""
    __tablename__ = 'card_verification_history'

    id = db.Column(db.Integer, primary_key=True)
    verification_id = db.Column(db.Integer, db.ForeignKey('collectible_verifications.id'), nullable=False)

    previous_status = db.Column(db.String(50))
    new_status = db.Column(db.String(50), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # Admin ID
    change_reason = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship('User', backref='card_verification_changes')

    def __repr__(self):
        return f'<CardVerificationHistory {self.previous_status} → {self.new_status}>'
