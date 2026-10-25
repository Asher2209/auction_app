from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ...extensions import db
from ...models import User

SALT = "password-reset"
MAX_AGE = 3600  # seconds


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def make_reset_token(user):
    # The password-hash tail makes the token single-use: it stops validating
    # as soon as the password changes.
    return _serializer().dumps({"id": user.id, "h": user.password_hash[-12:]})


def user_from_reset_token(token):
    try:
        data = _serializer().loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("id"))
    if user is None or user.password_hash[-12:] != data.get("h"):
        return None
    return user


# ---- email verification -----------------------------------------------------------------------------------------------
VERIFY_SALT = "email-verify"
VERIFY_MAX_AGE = 3 * 24 * 3600  # seconds


def make_email_token(user):
    # Carries the address it was sent to, so a link stops working if the account's email ever changes.
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=VERIFY_SALT).dumps({"id": user.id, "e": user.email})


def user_from_email_token(token):
    try:
        data = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=VERIFY_SALT).loads(token, max_age=VERIFY_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("id"))
    if user is None or user.email != data.get("e"):
        return None
    return user
