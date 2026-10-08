from datetime import timedelta

from flask import current_app
from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, IntegerField, MultipleFileField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError, Optional

from ... import timeutil
from ...models import utcnow
from ...services.category_questionnaires import get_category_questions

DT_FORMAT = "%Y-%m-%dT%H:%M"


class ProductForm(FlaskForm):
    title = StringField("Product name", validators=[DataRequired(), Length(min=3, max=200)])
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    description = TextAreaField("Description", validators=[DataRequired(), Length(min=10, max=5000)])
    starting_price = DecimalField(
        "Starting price", places=2,
        validators=[DataRequired(), NumberRange(min=1, max=10_000_000, message="Enter a price between 1 and 10,000,000.")],
    )
    auction_start = timeutil.LocalDateTimeField("Auction start", format=DT_FORMAT, validators=[DataRequired()])  # typed in site time, .data is UTC
    auction_end = timeutil.LocalDateTimeField("Auction end", format=DT_FORMAT, validators=[DataRequired()])
    images = MultipleFileField("Product images")

    # Common detail fields
    condition = SelectField("Condition", choices=[], validators=[Optional()])
    warranty = StringField("Warranty", validators=[Optional(), Length(max=200)])
    shipping_weight = StringField("Shipping Weight", validators=[Optional(), Length(max=50)])
    shipping_info = TextAreaField("Shipping Information", validators=[Optional()])
    storage_info = TextAreaField("Storage/Care Information", validators=[Optional()])

    # Electronics
    brand = StringField("Brand", validators=[Optional(), Length(max=100)])
    model = StringField("Model", validators=[Optional(), Length(max=100)])
    color = StringField("Color", validators=[Optional(), Length(max=50)])
    processor = StringField("Processor/CPU", validators=[Optional(), Length(max=100)])
    ram = StringField("RAM Memory", validators=[Optional(), Length(max=50)])
    storage = StringField("Storage", validators=[Optional(), Length(max=50)])
    screen_size = StringField("Screen Size", validators=[Optional(), Length(max=50)])
    battery = StringField("Battery Status", validators=[Optional(), Length(max=100)])

    # Collectibles
    artist_name = StringField("Artist/Creator", validators=[Optional(), Length(max=100)])
    edition = StringField("Edition", validators=[Optional(), Length(max=100)])
    authentication = StringField("Authentication", validators=[Optional(), Length(max=200)])
    rarity = SelectField("Rarity Level", choices=[], validators=[Optional()])
    provenance = TextAreaField("Provenance/History", validators=[Optional()])

    # Fashion
    size = StringField("Size", validators=[Optional(), Length(max=50)])
    fabric = StringField("Fabric/Material", validators=[Optional(), Length(max=100)])
    fit = StringField("Fit", validators=[Optional(), Length(max=100)])
    care_instructions = TextAreaField("Care Instructions", validators=[Optional()])
    designer = StringField("Designer/Brand", validators=[Optional(), Length(max=100)])

    # Books
    author = StringField("Author", validators=[Optional(), Length(max=100)])
    isbn = StringField("ISBN", validators=[Optional(), Length(max=20)])
    publication_year = IntegerField("Publication Year", validators=[Optional()])
    publisher = StringField("Publisher", validators=[Optional(), Length(max=100)])
    pages = IntegerField("Number of Pages", validators=[Optional()])
    language = StringField("Language", validators=[Optional(), Length(max=50)])
    binding = SelectField("Binding Type", choices=[], validators=[Optional()])

    # Sports
    sport_type = StringField("Sport Type", validators=[Optional(), Length(max=100)])
    sport_brand = StringField("Sport Brand", validators=[Optional(), Length(max=100)])
    size_sport = StringField("Size (Sport)", validators=[Optional(), Length(max=50)])
    material_sport = StringField("Material (Sport)", validators=[Optional(), Length(max=100)])

    # Home & Garden
    furniture_type = StringField("Item Type", validators=[Optional(), Length(max=100)])
    material_home = StringField("Material (Home)", validators=[Optional(), Length(max=100)])
    dimensions_home = StringField("Dimensions", validators=[Optional(), Length(max=100)])
    assembly_required = BooleanField("Assembly Required", validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        zone = timeutil.tz_name()
        self.auction_start.label.text = f"Auction start ({zone})"
        self.auction_end.label.text = f"Auction end ({zone})"

    def validate_auction_start(self, field):
        # small grace period so "start now" survives the round trip
        if field.data < utcnow() - timedelta(minutes=5):
            raise ValidationError("Start time cannot be in the past.")

    def validate_auction_end(self, field):
        if not self.auction_start.data:
            return
        length = field.data - self.auction_start.data
        lo = timedelta(minutes=current_app.config["MIN_AUCTION_MINUTES"])
        hi = timedelta(days=current_app.config["MAX_AUCTION_DAYS"])
        if length < lo:
            raise ValidationError(f"Auction must run for at least {current_app.config['MIN_AUCTION_MINUTES']} minutes.")
        if length > hi:
            raise ValidationError(f"Auction cannot run longer than {current_app.config['MAX_AUCTION_DAYS']} days.")
