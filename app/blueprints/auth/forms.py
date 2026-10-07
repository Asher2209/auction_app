import re

from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import (
    DataRequired, Email, EqualTo, Length, Regexp, ValidationError,
)

from ...models import User

PHONE_RE = r"^\+?[0-9 \-]{7,20}$"


def strong_password(form, field):
    pw = field.data or ""
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        raise ValidationError("Password must contain at least one letter and one digit.")


PASSWORD = [DataRequired(), Length(min=8, max=128), strong_password]


class RegisterForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[DataRequired(), Regexp(PHONE_RE, message="Enter a valid phone number.")])
    address = TextAreaField("Address", validators=[DataRequired(), Length(max=500)])
    role = SelectField("I want to", choices=[("buyer", "Buy (bid on items)"), ("seller", "Sell (list items)")])
    password = PasswordField("Password", validators=PASSWORD)
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", "Passwords must match.")])

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.strip().lower()).first():
            raise ValidationError("An account with this email already exists.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password", validators=PASSWORD)
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", "Passwords must match.")])


class ChangePasswordForm(FlaskForm):
    current = PasswordField("Current password", validators=[DataRequired()])
    password = PasswordField("New password", validators=PASSWORD)
    confirm = PasswordField("Confirm new password", validators=[DataRequired(), EqualTo("password", "Passwords must match.")])


class ProfileForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Phone", validators=[DataRequired(), Regexp(PHONE_RE, message="Enter a valid phone number.")])
    address = TextAreaField("Address", validators=[DataRequired(), Length(max=500)])
