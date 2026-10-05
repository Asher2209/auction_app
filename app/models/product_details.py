from ..extensions import db
from . import utcnow


class ProductDetails(db.Model):
    """Detailed product information with category-specific fields."""
    __tablename__ = "product_details"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), unique=True, nullable=False)

    # Common fields
    condition = db.Column(db.String(50))  # New, Like New, Good, Fair, Poor
    warranty = db.Column(db.String(200))
    shipping_weight = db.Column(db.String(50))  # e.g., "500g", "2kg"
    shipping_dimensions = db.Column(db.String(100))  # e.g., "10x10x10cm"
    shipping_info = db.Column(db.Text)
    storage_info = db.Column(db.Text)

    # Electronics-specific
    brand = db.Column(db.String(100))
    model = db.Column(db.String(100))
    color = db.Column(db.String(50))
    processor = db.Column(db.String(100))  # For laptops, phones
    ram = db.Column(db.String(50))  # e.g., "8GB", "16GB"
    storage = db.Column(db.String(50))  # e.g., "256GB SSD", "1TB HDD"
    battery = db.Column(db.String(100))  # For phones, laptops
    screen_size = db.Column(db.String(50))  # For phones, laptops

    # Collectibles-specific
    artist_name = db.Column(db.String(100))
    edition = db.Column(db.String(100))  # e.g., "Limited Edition", "First Edition"
    authentication = db.Column(db.String(200))  # e.g., "Certified by...", "With certificate of authenticity"
    rarity = db.Column(db.String(100))  # e.g., "Rare", "Very Rare", "Ultra Rare"
    provenance = db.Column(db.Text)  # History and origin

    # Fashion-specific
    size = db.Column(db.String(50))  # e.g., "M", "Large", "10"
    fabric = db.Column(db.String(100))  # e.g., "Cotton", "Silk", "Polyester"
    fit = db.Column(db.String(100))  # e.g., "Regular fit", "Slim fit"
    care_instructions = db.Column(db.Text)
    designer = db.Column(db.String(100))

    # Books-specific
    author = db.Column(db.String(100))
    isbn = db.Column(db.String(20))
    publication_year = db.Column(db.Integer)
    publisher = db.Column(db.String(100))
    pages = db.Column(db.Integer)
    language = db.Column(db.String(50))  # e.g., "English", "Spanish"
    binding = db.Column(db.String(50))  # e.g., "Hardcover", "Paperback"

    # Sports-specific
    sport_type = db.Column(db.String(100))  # e.g., "Football", "Basketball"
    sport_brand = db.Column(db.String(100))
    size_sport = db.Column(db.String(50))  # e.g., "Size 10", "Medium"
    material_sport = db.Column(db.String(100))

    # Home & Garden-specific
    furniture_type = db.Column(db.String(100))  # e.g., "Sofa", "Table"
    material_home = db.Column(db.String(100))  # e.g., "Wood", "Metal"
    dimensions_home = db.Column(db.String(100))
    assembly_required = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    product = db.relationship("Product", backref=db.backref("details", uselist=False, cascade="all, delete-orphan"))
