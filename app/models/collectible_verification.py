from datetime import datetime
from ..extensions import db
from . import utcnow

class CollectibleVerification(db.Model):
    """Store collectible verification details for products (both graded and ungraded cards)"""
    __tablename__ = 'collectible_verifications'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), unique=True, nullable=False)
    collectible_card_id = db.Column(db.Integer, db.ForeignKey('collectible_cards.id'))

    # Collectible type (Tier 1: graded cards, coins, etc. OR ungraded trading cards)
    collectible_type = db.Column(db.String(100), nullable=False)  # 'trading_card', 'coin', 'comic', 'autograph', etc.
    is_graded = db.Column(db.Boolean, default=False)  # True for graded items, False for seller-assessed

    # For GRADED items only:
    grader = db.Column(db.String(100))  # PSA, Beckett, CGC, PCGS, NGC, etc.
    certificate_number = db.Column(db.String(100), index=True)  # Optional for graded items
    grade = db.Column(db.String(20))  # PSA 10, Gem MT 9, etc.
    year = db.Column(db.Integer)
    grader_item_name = db.Column(db.String(255))  # e.g., "Pokémon Charizard Base Set"
    grader_cert_url = db.Column(db.String(500))  # Link to grader's certificate page
    grader_response = db.Column(db.Text)  # JSON response from grader API

    # For UNGRADED trading cards:
    # The card details are stored in CollectibleCard model

    # Verification status (enhanced workflow)
    # pending → submitted → under_review → more_info_needed → verified → approved/rejected
    verification_status = db.Column(db.String(50), default='pending')
    verification_date = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # admin user ID

    # Photo verification
    slab_photo_urls = db.Column(db.Text)  # JSON array of photo URLs (for graded items)
    photos_verified = db.Column(db.Boolean, default=False)
    photos_verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # admin user ID
    photos_verified_date = db.Column(db.DateTime)

    # Risk management
    duplicate_flag = db.Column(db.Boolean, default=False)  # True if cert used in previous listing
    previous_listing_id = db.Column(db.Integer)  # Link to previous product using same cert

    # Verification workflow for ungraded cards
    admin_notes = db.Column(db.Text)  # Admin's detailed notes
    rejection_reason = db.Column(db.String(255))  # Why it was rejected
    seller_response = db.Column(db.Text)  # Seller's response to "more info needed" request
    submission_count = db.Column(db.Integer, default=1)  # Track resubmissions

    # Timestamps
    notes = db.Column(db.Text)  # Legacy field
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    product = db.relationship('Product', backref=db.backref('collectible_verification', uselist=False))
    collectible_card = db.relationship('CollectibleCard', foreign_keys=[collectible_card_id])
    verification_history = db.relationship('CardVerificationHistory', backref='verification', cascade='all, delete-orphan')
    checklists = db.relationship('CardVerificationChecklist', backref='verification', cascade='all, delete-orphan')
    verified_by_user = db.relationship('User', foreign_keys=[verified_by], backref='verified_collectibles')
    photos_verified_by_user = db.relationship('User', foreign_keys=[photos_verified_by], backref='photo_verified_collectibles')

    def __repr__(self):
        if self.is_graded:
            return f'<CollectibleVerification {self.certificate_number} ({self.grader})>'
        else:
            return f'<CollectibleVerification {self.product_id} (ungraded)>'


class VerificationLog(db.Model):
    """Audit trail for all verification activities"""
    __tablename__ = 'verification_logs'

    id = db.Column(db.Integer, primary_key=True)
    collectible_id = db.Column(db.Integer, db.ForeignKey('collectible_verifications.id'), nullable=False)

    action = db.Column(db.String(100), nullable=False)  # 'api_lookup', 'photo_upload', 'manual_review', etc.
    status = db.Column(db.String(50), nullable=False)  # 'success', 'failure', 'pending'
    details = db.Column(db.Text)  # JSON details
    performed_by = db.Column(db.String(100))  # user or system
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    collectible = db.relationship('CollectibleVerification', backref='verification_logs')

    def __repr__(self):
        return f'<VerificationLog {self.action} - {self.status}>'


class SupportedGrader(db.Model):
    """Registry of supported grading companies and their APIs"""
    __tablename__ = 'supported_graders'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)  # PSA, PCGS, NGC, etc.

    # API Configuration
    api_endpoint = db.Column(db.String(500))
    api_key_required = db.Column(db.Boolean, default=False)
    api_key_name = db.Column(db.String(50))  # stored in config/env

    # Certification types this grader handles
    cert_types = db.Column(db.String(500))  # JSON: ["trading_card", "coin", "comic"]

    # Lookup method
    lookup_method = db.Column(db.String(50))  # 'cert_number', 'serial', 'batch'
    lookup_instructions = db.Column(db.Text)

    # Status
    is_active = db.Column(db.Boolean, default=True)
    last_tested = db.Column(db.DateTime)
    is_working = db.Column(db.Boolean, default=None)  # None = untested, True = working, False = down

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<SupportedGrader {self.name}>'
