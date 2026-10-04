from datetime import timedelta

from flask import current_app
from flask_wtf import FlaskForm
from wtforms import DecimalField, MultipleFileField, SelectField, StringField, TextAreaField
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError

from ...models import utcnow

DT_FORMAT = "%Y-%m-%dT%H:%M"


class ProductForm(FlaskForm):
    title = StringField("Product name", validators=[DataRequired(), Length(min=3, max=200)])
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    description = TextAreaField("Description", validators=[DataRequired(), Length(min=10, max=5000)])
    starting_price = DecimalField(
        "Starting price", places=2,
        validators=[DataRequired(), NumberRange(min=1, max=10_000_000, message="Enter a price between 1 and 10,000,000.")],
    )
    auction_start = DateTimeLocalField("Auction start (UTC)", format=DT_FORMAT, validators=[DataRequired()])
    auction_end = DateTimeLocalField("Auction end (UTC)", format=DT_FORMAT, validators=[DataRequired()])
    images = MultipleFileField("Product images")

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
