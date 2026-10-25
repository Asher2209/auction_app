"""Sign in with Google (OpenID Connect, through Authlib).

Off unless GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set: no button is shown and the routes answer 404. Authlib
checks the ID token (signature, issuer, audience, expiry and the nonce it put in the request) before we see the claims.

Who a Google sign-in belongs to:
  - the account already linked to that Google identity (`sub`, which never changes, unlike the email address);
  - otherwise the account with the same email, but only if that account has confirmed its address. Linking to an
    unconfirmed one would let someone register a victim's address with their own password and wait for the victim;
  - otherwise nobody yet: the visitor finishes signing up (role, phone, address, terms) and a new account is made.
"""
from authlib.integrations.flask_client import OAuth, OAuthError  # noqa: F401  (OAuthError is caught by the routes)
from flask import current_app

METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"


def init_app(app):
    oauth = OAuth(app)
    oauth.register("google", server_metadata_url=METADATA_URL, client_kwargs={"scope": "openid email profile"},
                   client_id=app.config.get("GOOGLE_CLIENT_ID"), client_secret=app.config.get("GOOGLE_CLIENT_SECRET"))
    app.extensions["google_oauth"] = oauth


def enabled():
    return bool(current_app.config.get("GOOGLE_CLIENT_ID") and current_app.config.get("GOOGLE_CLIENT_SECRET"))


def client():
    return current_app.extensions["google_oauth"].google


def profile(token):
    """The verified claims from a token response, as {"sub", "email", "email_verified", "name"}."""
    info = token.get("userinfo") or {}
    return {
        "sub": str(info.get("sub") or ""),
        "email": str(info.get("email") or "").strip().lower(),
        "email_verified": info.get("email_verified") is True,
        "name": str(info.get("name") or "").strip()[:120],
    }
