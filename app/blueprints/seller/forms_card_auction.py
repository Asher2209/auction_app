from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, SelectField
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, NumberRange, Optional

DT_FORMAT = "%Y-%m-%dT%H:%M"
DURATIONS = [(1, "1 hour"), (6, "6 hours"), (24, "1 day"), (72, "3 days"), (168, "7 days"), (336, "14 days"),
             (720, "30 days")]


class CardAuctionForm(FlaskForm):
    starting_bid = DecimalField(
        "Starting bid", places=2,
        validators=[DataRequired(), NumberRange(min=1, max=10_000_000, message="Enter a bid between 1 and 10,000,000.")])
    duration_hours = SelectField("Auction duration", coerce=int, choices=DURATIONS, default=168,
                                 validators=[DataRequired()])
    start_time = DateTimeLocalField("Start time (UTC). Leave empty to start now", format=DT_FORMAT,
                                    validators=[Optional()])
    confirm_ownership = BooleanField(
        "I own this physical card and will send it to the winner once the payment is confirmed",
        validators=[DataRequired(message="Please confirm before listing the card.")])
