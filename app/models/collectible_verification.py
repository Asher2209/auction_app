from datetime import datetime
from ..extensions import db

class CollectibleVerification(db.Model):
    """Store collectible verification details for products"""
    __tablename__ = 'collectible_verifications'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), unique=True, nullable=False)

    # Collectible type (Tier 1: graded cards, coins, etc.)
    collectible_type = db.Column(db.String(100), nullable=False)  # 'trading_card', 'coin', 'comic', 'autograph', etc.
    grader = db.Column(db.String(100), nullable=False)  # PSA, Beckett, CGC, PCGS, NGC, etc.

    # Certificate details
    certificate_number = db.Column(db.String(100), nullable=False, unique=True, index=True)
    grade = db.Column(db.String(20))  # PSA 10, Gem MT 9, etc.
    year = db.Column(db.Integer)

    # Verification status
    verification_status = db.Column(db.String(50), default='pending')  # pending, verified, failed, manual_review
    verification_date = db.Column(db.DateTime)
    verified_by = db.Column(db.String(100))  # admin user or API name

    # Grader details for lookup
    grader_item_name = db.Column(db.String(255))  # e.g., "Pokémon Charizard Base Set"
    grader_cert_url = db.Column(db.String(500))  # Link to grader's certificate page
    grader_response = db.Column(db.Text)  # JSON response from grader API

    # Photo verification
    slab_photo_urls = db.Column(db.Text)  # JSON array of photo URLs
    photos_verified = db.Column(db.Boolean, default=False)
    photos_verified_by = db.Column(db.String(100))  # admin user
    photos_verified_date = db.Column(db.DateTime)

    # Risk management
    duplicate_flag = db.Column(db.Boolean, default=False)  # True if cert used in previous listing
    previous_listing_id = db.Column(db.Integer)  # Link to previous product using same cert

    # Notes and audit trail
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    product = db.relationship('Product', backref='collectible_verification', uselist=False)

    def __repr__(self):
        return f'<CollectibleVerification {self.certificate_number} ({self.grader})>'


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
