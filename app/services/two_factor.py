"""Two-step sign-in with an authenticator app (TOTP, RFC 6238) and single-use recovery codes.

A code is accepted for the current 30-second step and one step either side (phone clocks drift), and never twice:
the last accepted step is stored, and any code for that step or an earlier one is refused, so a code seen over
someone's shoulder cannot be replayed. Recovery codes are stored only as password hashes and each works once.
"""
import hmac
import json
import secrets
import time
from io import BytesIO

import pyotp
import qrcode
import qrcode.image.svg
from werkzeug.security import check_password_hash, generate_password_hash

from ..models import utcnow

ISSUER = "MintLot"
STEP = 30  # seconds per code
DRIFT = 1  # steps accepted either side of now
RECOVERY_COUNT = 10


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(secret, email):
    return pyotp.TOTP(secret, interval=STEP).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_svg(uri):
    """The setup QR code as inline SVG (no file on disk, no request to anyone else)."""
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    out = BytesIO()
    img.save(out)
    return out.getvalue().decode("utf-8").split("?>", 1)[-1].strip()  # drop the XML declaration for inline use


def _digits(code):
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def matching_step(secret, code, now=None):
    """The 30-second step `code` belongs to, if it is valid for `secret` near `now`; otherwise None."""
    code = _digits(code)
    if not secret or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret, interval=STEP)
    step_now = int((now if now is not None else time.time()) // STEP)
    for step in range(step_now - DRIFT, step_now + DRIFT + 1):
        if hmac.compare_digest(totp.at(step * STEP), code):
            return step
    return None


def verify_code(user, code, now=None):
    """True for a valid, unused code; records its step so it cannot be used again. The caller commits."""
    step = matching_step(user.totp_secret, code, now)
    if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
        return False
    user.totp_last_step = step
    return True


def _normalise_recovery(code):
    return "".join(ch for ch in str(code or "").lower() if ch.isalnum())


def new_recovery_codes():
    """Ten fresh codes to show the user once, and the JSON list of their hashes to store."""
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_COUNT)]
    return codes, json.dumps([generate_password_hash(_normalise_recovery(c)) for c in codes])


def recovery_left(user):
    return len(json.loads(user.totp_recovery or "[]"))


def use_recovery_code(user, code):
    """True if `code` is one of the user's unused recovery codes, which is then spent. The caller commits."""
    code = _normalise_recovery(code)
    if len(code) != 12:
        return False
    hashes = json.loads(user.totp_recovery or "[]")
    for h in hashes:
        if check_password_hash(h, code):
            hashes.remove(h)
            user.totp_recovery = json.dumps(hashes)
            return True
    return False


def check(user, code, now=None):
    """A sign-in or confirmation: an authenticator code, or failing that a recovery code."""
    return verify_code(user, code, now) or use_recovery_code(user, code)


def enable(user, secret, step):
    """Turn two-step sign-in on with a secret the user has just proven (step: the code they typed). Returns the recovery codes."""
    codes, hashed = new_recovery_codes()
    user.totp_secret = secret
    user.totp_enabled_at = utcnow()
    user.totp_last_step = step
    user.totp_recovery = hashed
    return codes


def regenerate_recovery_codes(user):
    codes, hashed = new_recovery_codes()
    user.totp_recovery = hashed
    return codes


def disable(user):
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    user.totp_recovery = None
