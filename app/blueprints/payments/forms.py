from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Regexp, ValidationError

from ...services import payment_service as ps


class CardForm(FlaskForm):
    card_holder = StringField("Name on card", validators=[DataRequired(), Length(min=2, max=80)],
                              render_kw={"autocomplete": "cc-name"})
    card_number = StringField("Card number", validators=[DataRequired(), Length(max=30)],
                              render_kw={"autocomplete": "cc-number", "inputmode": "numeric", "placeholder": "4242 4242 4242 4242"})
    expiry = StringField("Expiry (MM/YY)", validators=[DataRequired(), Length(max=7)],
                         render_kw={"autocomplete": "cc-exp", "placeholder": "MM/YY"})
    cvv = PasswordField("CVV", validators=[DataRequired(), Regexp(r"^[0-9]{3,4}$", message="Enter the 3 or 4 digit CVV.")],
                        render_kw={"autocomplete": "cc-csc", "inputmode": "numeric", "maxlength": 4})

    def validate_card_number(self, field):
        if ps.clean_card_number(field.data) is None:
            raise ValidationError("Enter a valid card number.")

    def validate_expiry(self, field):
        if not ps.expiry_ok(field.data):
            raise ValidationError("Enter a valid, unexpired date as MM/YY.")


class UpiForm(FlaskForm):
    upi_id = StringField("UPI ID", validators=[DataRequired(), Length(max=100)],
                         render_kw={"placeholder": "name@bank"})

    def validate_upi_id(self, field):
        if not ps.UPI_RE.match((field.data or "").strip()):
            raise ValidationError("Enter a valid UPI ID such as name@bank.")


class WalletForm(FlaskForm):
    provider = SelectField("Wallet", choices=[(w, w) for w in ps.WALLETS])
    mobile = StringField("Registered mobile number", validators=[DataRequired(), Regexp(r"^[0-9]{10}$", message="Enter a 10 digit mobile number.")],
                         render_kw={"inputmode": "numeric", "autocomplete": "tel-national"})


FORMS = {"card": CardForm, "upi": UpiForm, "wallet": WalletForm}
