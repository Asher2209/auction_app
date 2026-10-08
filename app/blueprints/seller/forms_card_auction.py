from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, SelectField
from wtforms.validators import DataRequired, NumberRange, Optional

from ... import timeutil

DT_FORMAT = "%Y-%m-%dT%H:%M"
DURATIONS = [(1, "1 hour"), (6, "6 hours"), (24, "1 day"), (72, "3 days"), (168, "7 days"), (336, "14 days"),
             (720, "30 days")]


class CardAuctionForm(FlaskForm):
    starting_bid = DecimalField(
        "Starting bid", places=2,
        validators=[DataRequired(), NumberRange(min=1, max=10_000_000, message="Enter a bid between 1 and 10,000,000.")])
    duration_hours = SelectField("Auction duration", coerce=int, choices=DURATIONS, default=168,
                                 validators=[DataRequired()])
    start_time = timeutil.LocalDateTimeField("Start time. Leave empty to start now", format=DT_FORMAT,
                                             validators=[Optional()])  # typed in site time, .data is UTC
    confirm_ownership = BooleanField(
        "I own this physical card and will send it to the winner once the payment is confirmed",
        validators=[DataRequired(message="Please confirm before listing the card.")])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time.label.text = f"Start time ({timeutil.tz_name()}). Leave empty to start now"
