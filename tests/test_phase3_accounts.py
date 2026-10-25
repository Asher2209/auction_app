"""Phase 3, accounts.

  Email verification ...... email_*   (a new account is signed in at once; bidding, selling and paying wait for the link)
  Two-step sign-in ........ totp_*    (authenticator codes after the password; single-use recovery codes)
  Signed-in devices ....... devices_* (every login is a row; ending the row ends that login, wherever it is)
  Wallet sign-in .......... siwe_*    (EIP-4361; only a wallet an account has already proven can sign in)
  Google sign-in .......... google_*  (off unless configured; never attaches to an account whose email is unconfirmed)
"""
import importlib.util
import json
import re
import time
from pathlib import Path

import pyotp
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eth_account import Account
from eth_account.messages import encode_defunct
from flask import g, redirect
from flask.testing import FlaskClient
from web3 import Web3

from app.blueprints.auth.tokens import make_email_token, make_reset_token
from app.extensions import db, mail
from app.models import User, UserSession, utcnow
from app.services import google_login
from app.services import sessions as user_sessions

from .conftest import PASSWORD, login, make_user, prove_wallet
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_payments import card, pay, won

ROOT = Path(__file__).resolve().parents[1]
REG = {"name": "Nina New", "email": "nina@t.test", "phone": "9876543210", "address": "1 Main St", "role": "buyer",
       "password": "Passw0rdX", "confirm": "Passw0rdX", "accept_terms": "y"}


def register(client, **over):
    with mail.record_messages() as outbox:
        r = client.post("/auth/register", data={**REG, **over})
    return r, outbox


def link_in(message):
    return re.search(r"https?://\S+/auth/verify-email/\S+", message.body).group(0)


def unverify(user):
    user.email_verified_at = None
    db.session.commit()
    return user


# =================================== email verification ========================================================================
def test_email_registering_signs_you_in_and_sends_one_confirmation_link(client):
    r, outbox = register(client)
    assert r.status_code == 302 and r.location.endswith("/dashboard")
    user = User.query.filter_by(email=REG["email"]).one()
    assert user.email_verified_at is None
    assert [m.recipients for m in outbox] == [[REG["email"]]] and "Confirm your email address" in outbox[0].subject
    page = client.get("/buyer/").get_data(as_text=True)  # signed in, with the reminder
    assert "Confirm your email address to bid" in page and "/auth/verify-email/resend" in page


def test_email_the_link_confirms_the_address_and_the_reminder_goes(client):
    _, outbox = register(client)
    r = client.get(link_in(outbox[0]))
    assert r.status_code == 302
    user = User.query.filter_by(email=REG["email"]).one()
    assert user.email_verified_at is not None
    assert "Confirm your email address to bid" not in client.get("/buyer/").get_data(as_text=True)
    first = user.email_verified_at
    client.get(link_in(outbox[0]))  # opening it again is harmless and keeps the first time
    db.session.expire_all()
    assert db.session.get(User, user.id).email_verified_at == first


def test_email_a_tampered_or_stale_link_confirms_nothing(client, users):
    user = unverify(users["buyer"])
    token = make_email_token(user)
    assert client.get(f"/auth/verify-email/{token[:-2]}xx").status_code == 302
    user.email = "changed@t.test"  # the link names the address it was sent to
    db.session.commit()
    client.get(f"/auth/verify-email/{token}")
    db.session.expire_all()
    assert db.session.get(User, user.id).email_verified_at is None


def test_email_an_unconfirmed_buyer_cannot_bid_until_they_confirm(client, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Lamp", 100)
    unverify(users["buyer"])
    login(client, "buyer@t.test")
    r = client.post(f"/auctions/{a.id}/bid", data={"amount": "150"}, headers={"Accept": "application/json"})
    assert r.status_code == 403 and "Confirm your email address" in r.get_json()["error"]
    users["buyer"].email_verified_at = utcnow()
    db.session.commit()
    r = client.post(f"/auctions/{a.id}/bid", data={"amount": "150"}, headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_email_an_unconfirmed_seller_cannot_submit_a_card(client, users):
    unverify(users["seller"])
    login(client, "seller@t.test")
    r = client.get("/seller/cards/new")
    assert r.status_code == 302 and r.location.endswith("/dashboard")
    users["seller"].email_verified_at = utcnow()
    db.session.commit()
    assert client.get("/seller/cards/new").status_code == 200


def test_email_an_unconfirmed_winner_cannot_pay(app, users, cats):  # noqa: F811
    a = won(users, cats)
    unverify(users["buyer"])
    c = app.test_client()
    login(c, "buyer@t.test")
    assert pay(c, a, "card", card()).status_code == 302
    db.session.expire_all()
    assert a.payment.payment_status == "pending"
    r = c.post(f"/payments/{a.id}/crypto/prepare", json={"accept_terms": True})
    assert r.status_code == 403 and r.get_json()["ok"] is False


def test_email_a_new_link_can_be_sent_three_times_an_hour(client, users):
    unverify(users["buyer"])
    login(client, "buyer@t.test")
    with mail.record_messages() as outbox:
        codes = [client.post("/auth/verify-email/resend").status_code for _ in range(4)]
    assert codes == [302, 302, 302, 429] and len(outbox) == 3


def test_email_an_already_confirmed_account_is_not_sent_another_link(client, users):
    login(client, "buyer@t.test")
    with mail.record_messages() as outbox:
        client.post("/auth/verify-email/resend")
    assert outbox == []


def test_email_the_resend_button_only_returns_you_to_this_site(client, users):
    unverify(users["buyer"])
    login(client, "buyer@t.test")
    r = client.post("/auth/verify-email/resend", data={"next": "https://evil.example/x"})
    assert r.location.endswith("/dashboard")


MIGRATION = ROOT / "migrations" / "versions" / "k21emailverify01_email_verification.py"


def test_email_the_migration_counts_existing_accounts_as_confirmed():
    spec = importlib.util.spec_from_file_location("k21", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, created_at DATETIME NOT NULL)"))
        conn.execute(sa.text("INSERT INTO users (created_at) VALUES ('2026-01-02 03:04:05')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert conn.execute(sa.text("SELECT email_verified_at FROM users")).scalar() == "2026-01-02 03:04:05"
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert "email_verified_at" not in {c["name"] for c in sa.inspect(conn).get_columns("users")}


def test_email_new_registrations_through_the_form_are_never_born_confirmed(client):
    register(client, email="x@t.test")
    assert User.query.filter_by(email="x@t.test").one().email_verified_at is None
    assert make_user("y@t.test").email_verified_at is not None  # the test helper's accounts are confirmed


# =================================== two-step sign-in =========================================================================
def code(secret, steps_ahead=0):
    """A valid code; steps_ahead=1 is the next 30-second step's (accepted for clock drift), so two in a row both count."""
    return pyotp.TOTP(secret).at(time.time() + 30 * steps_ahead)


def turn_on(client, email="buyer@t.test"):
    login(client, email)
    client.get("/auth/two-factor/setup")
    with client.session_transaction() as s:
        secret = s["totp_setup"]
    # setup takes the previous step's code, sign-in the current one, a later confirmation the next one: each is newer
    page = client.post("/auth/two-factor/setup", data={"code": code(secret, -1)}).get_data(as_text=True)
    client.post("/auth/logout")
    return secret, re.findall(r"<code>([0-9a-f]{6}-[0-9a-f]{6})</code>", page)


def signed_in(client, path="/buyer/"):
    g.pop("_login_user", None)  # the test keeps one app context open, so forget the last request's user (see device())
    return client.get(path).status_code == 200


def test_totp_setup_shows_a_local_qr_and_key_and_a_wrong_code_changes_nothing(client, users):
    login(client, "buyer@t.test")
    page = client.get("/auth/two-factor/setup").get_data(as_text=True)
    with client.session_transaction() as s:
        secret = s["totp_setup"]
    svg = page.split("<svg", 1)[1].split("</svg>", 1)[0]
    assert "href" not in svg and "<image" not in svg  # drawn inline: no request to anyone else
    assert " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)) in page
    r = client.post("/auth/two-factor/setup", data={"code": "000000"})
    assert r.status_code == 200 and "That code is not right" in r.get_data(as_text=True)
    assert not db.session.get(User, users["buyer"].id).two_factor_enabled


def test_totp_turning_it_on_shows_ten_recovery_codes_once_and_stores_only_hashes(client, users):
    secret, codes = turn_on(client)
    user = db.session.get(User, users["buyer"].id)
    assert user.two_factor_enabled and user.totp_secret == secret and len(codes) == len(set(codes)) == 10
    assert len(json.loads(user.totp_recovery)) == 10 and not any(c.replace("-", "") in user.totp_recovery for c in codes)
    login(client, "buyer@t.test")
    assert client.get("/auth/two-factor/setup").status_code == 302  # already on: nothing to set up again


def test_totp_the_password_alone_no_longer_signs_you_in(client, users):
    secret, _ = turn_on(client)
    r = login(client, "buyer@t.test")
    assert r.status_code == 302 and r.location.endswith("/auth/two-factor") and not signed_in(client)
    r = client.post("/auth/two-factor", data={"code": code(secret, 1)})
    assert r.status_code == 302 and signed_in(client)


def test_totp_a_used_code_cannot_be_used_again(client, users):
    secret, _ = turn_on(client)
    login(client, "buyer@t.test")
    used = code(secret, 1)
    client.post("/auth/two-factor", data={"code": used})
    client.post("/auth/logout")
    login(client, "buyer@t.test")
    r = client.post("/auth/two-factor", data={"code": used})
    assert r.status_code == 200 and not signed_in(client)


def test_totp_a_recovery_code_signs_you_in_once(client, users):
    _, codes = turn_on(client)
    login(client, "buyer@t.test")
    assert client.post("/auth/two-factor", data={"code": codes[0].upper()}).status_code == 302 and signed_in(client)
    client.post("/auth/logout")
    login(client, "buyer@t.test")
    assert client.post("/auth/two-factor", data={"code": codes[0]}).status_code == 200 and not signed_in(client)
    assert len(json.loads(db.session.get(User, users["buyer"].id).totp_recovery)) == 9


def test_totp_wrong_codes_are_limited_per_account(client, users):
    turn_on(client)
    login(client, "buyer@t.test")
    codes = [client.post("/auth/two-factor", data={"code": "123456"}).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_totp_the_code_step_expires_and_cannot_be_reached_without_the_password(client, users):
    secret, _ = turn_on(client)
    assert client.get("/auth/two-factor").status_code == 302  # no password checked yet
    login(client, "buyer@t.test")
    with client.session_transaction() as s:
        s["2fa_pending"] = {**s["2fa_pending"], "at": int(time.time()) - 301}
    r = client.post("/auth/two-factor", data={"code": code(secret, 1)})
    assert r.status_code == 302 and r.location.endswith("/auth/login") and not signed_in(client)


def test_totp_turning_it_off_needs_the_password_and_a_code(client, users):
    secret, _ = turn_on(client)
    login(client, "buyer@t.test")
    client.post("/auth/two-factor", data={"code": code(secret)})
    assert signed_in(client)
    r = client.post("/auth/two-factor/manage", data={"action": "disable", "password": "wrong", "code": code(secret, 1)})
    assert r.status_code == 200 and db.session.get(User, users["buyer"].id).two_factor_enabled
    client.post("/auth/two-factor/manage", data={"action": "disable", "password": PASSWORD, "code": code(secret, 1)})
    db.session.expire_all()
    user = db.session.get(User, users["buyer"].id)
    assert not user.two_factor_enabled and user.totp_secret is None and user.totp_recovery is None


def test_totp_new_recovery_codes_replace_the_old_ones(client, users):
    secret, old = turn_on(client)
    login(client, "buyer@t.test")
    client.post("/auth/two-factor", data={"code": code(secret)})
    assert signed_in(client)
    page = client.post("/auth/two-factor/manage",
                       data={"action": "regenerate", "password": PASSWORD, "code": code(secret, 1)}).get_data(as_text=True)
    new = re.findall(r"<code>([0-9a-f]{6}-[0-9a-f]{6})</code>", page)
    assert len(new) == 10 and not set(new) & set(old)
    client.post("/auth/logout")
    login(client, "buyer@t.test")
    assert client.post("/auth/two-factor", data={"code": old[1]}).status_code == 200 and not signed_in(client)


def test_totp_the_account_page_offers_it_and_urges_admins(client, users):
    login(client, "admin@t.test")
    page = client.get("/auth/profile").get_data(as_text=True)
    assert "/auth/two-factor/setup" in page and "Strongly recommended for admin accounts" in page


MIGRATION_2FA = ROOT / "migrations" / "versions" / "l22twofactor01_two_step_sign_in.py"


def test_totp_the_migration_adds_the_columns_switched_off():
    spec = importlib.util.spec_from_file_location("l22", MIGRATION_2FA)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        row = conn.execute(sa.text("SELECT totp_secret, totp_enabled_at, totp_last_step, totp_recovery FROM users")).first()
        assert tuple(row) == (None, None, None, None)
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert {c["name"] for c in sa.inspect(conn).get_columns("users")} == {"id"}


# =================================== signed-in devices ========================================================================
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile Safari/604.1"


class Device(FlaskClient):
    """A separate browser. Flask-Login caches the signed-in user on `g`, and the test's app context outlives each
    request, so without forgetting it one browser's sign-out would look like every browser's."""
    def open(self, *args, **kwargs):
        g.pop("_login_user", None)
        return super().open(*args, **kwargs)


def device(app, ua, email="buyer@t.test"):
    """A separate browser, signed in, that always sends the same user agent (the strong session check needs that)."""
    app.test_client_class = Device
    c = app.test_client()
    app.test_client_class = None
    c.environ_base["HTTP_USER_AGENT"] = ua
    login(c, email)
    return c


def sid_of(user, ua):
    """The id of `user`'s live session from browser `ua` (read from the database: opening the test client's session
    from outside a request would sign that browser out, because the strong session check sees a different client)."""
    return UserSession.query.filter_by(user_id=user.id, user_agent=ua, revoked_at=None).one().id


def test_devices_each_login_is_listed_and_this_device_is_marked(app, users):
    laptop, phone = device(app, CHROME), device(app, IPHONE)
    assert signed_in(laptop) and signed_in(phone)
    page = laptop.get("/auth/sessions").get_data(as_text=True)
    assert "Chrome on Windows" in page and "Safari on iPhone" in page and page.count("This device") == 1
    assert UserSession.query.filter_by(user_id=users["buyer"].id, revoked_at=None).count() == 2


def test_devices_signing_out_one_device_reaches_it_on_its_next_request(app, users):
    laptop, phone = device(app, CHROME), device(app, IPHONE)
    phone_sid = sid_of(users["buyer"], IPHONE)
    assert laptop.post(f"/auth/sessions/{phone_sid}/end").status_code == 302
    assert not signed_in(phone) and signed_in(laptop)


def test_devices_sign_out_all_others_keeps_only_this_one(app, users):
    laptop, phone, tablet = device(app, CHROME), device(app, IPHONE), device(app, IPHONE)
    laptop.post("/auth/sessions/end-others")
    assert signed_in(laptop) and not signed_in(phone) and not signed_in(tablet)


def test_devices_logging_out_ends_the_row(app, users):
    laptop = device(app, CHROME)
    laptop.post("/auth/logout")
    assert UserSession.query.filter(UserSession.revoked_at.is_(None)).count() == 0


def test_devices_nobody_can_end_another_accounts_session(app, users):
    mine, theirs = device(app, CHROME), device(app, CHROME, "seller@t.test")
    their_sid = sid_of(users["seller"], CHROME)
    mine.post(f"/auth/sessions/{their_sid}/end")
    assert signed_in(theirs, "/seller/collectibles")


def test_devices_changing_the_password_signs_out_the_others_but_not_this_one(app, users):
    laptop, phone = device(app, CHROME), device(app, IPHONE)
    r = laptop.post("/auth/change-password", data={"current": PASSWORD, "password": "N3wPassword", "confirm": "N3wPassword"},
                    follow_redirects=True)
    assert "1 other signed-in device signed out" in r.get_data(as_text=True)
    assert signed_in(laptop) and not signed_in(phone)


def test_devices_a_password_reset_signs_out_everywhere(app, users):
    laptop = device(app, CHROME)
    token = make_reset_token(users["buyer"])
    app.test_client().post(f"/auth/reset-password/{token}", data={"password": "N3wPassword", "confirm": "N3wPassword"})
    assert not signed_in(laptop)


def test_devices_turning_on_two_step_sign_in_signs_out_the_others(app, users):
    laptop, phone = device(app, CHROME), device(app, IPHONE)
    laptop.get("/auth/two-factor/setup")
    with laptop.session_transaction() as s:
        secret = s["totp_setup"]
    laptop.post("/auth/two-factor/setup", data={"code": code(secret)})
    assert signed_in(laptop) and not signed_in(phone)


def test_devices_a_login_with_no_device_record_is_ended(app, users):
    laptop = device(app, CHROME)
    with laptop.session_transaction() as s:
        s.pop(user_sessions.KEY)
    assert not signed_in(laptop)


def test_devices_labels_are_plain_and_never_fail():
    assert user_sessions.device_label(CHROME) == "Chrome on Windows"
    assert user_sessions.device_label(IPHONE) == "Safari on iPhone"
    assert user_sessions.device_label("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0") == "Firefox on Linux"
    assert user_sessions.device_label(None) == "Unknown browser"


MIGRATION_DEVICES = ROOT / "migrations" / "versions" / "m23sessions01_signed_in_devices.py"


def test_devices_the_migration_creates_and_drops_the_table():
    spec = importlib.util.spec_from_file_location("m23", MIGRATION_DEVICES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        cols = {c["name"] for c in sa.inspect(conn).get_columns("user_sessions")}
        assert cols == {"id", "user_id", "created_at", "last_seen_at", "ip", "user_agent", "revoked_at"}
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert "user_sessions" not in sa.inspect(conn).get_table_names()


# =================================== wallet sign-in (EIP-4361) ================================================================
WALLET_KEY, STRANGER_KEY = "0x" + "6e" * 32, "0x" + "7f" * 32  # throwaway test keys
WALLET, STRANGER = Account.from_key(WALLET_KEY).address, Account.from_key(STRANGER_KEY).address


def sign(message, key):
    return Web3.to_hex(Account.sign_message(encode_defunct(text=message), private_key=key).signature)


def link_wallet(app, email="buyer@t.test", key=WALLET_KEY):
    c = app.test_client()
    login(c, email)
    assert prove_wallet(c, key).get_json()["ok"]
    c.post("/auth/logout")


def wallet_sign_in(client, address, key, **extra):
    message = client.post("/auth/wallet-login/challenge", json={"address": address}).get_json()["message"]
    return client.post("/auth/wallet-login/verify", json={"address": address, "signature": sign(message, key), **extra})


def test_siwe_the_message_is_standard_and_says_it_costs_nothing(app, client):
    message = client.post("/auth/wallet-login/challenge", json={"address": WALLET}).get_json()["message"]
    lines = message.split("\n")
    assert lines[0] == "localhost wants you to sign in with your Ethereum account:" and lines[1] == WALLET
    assert "does not send a transaction, cost gas" in message
    for field in ("URI: http://localhost/", "Version: 1", f"Chain ID: {app.config['CHAIN_ID']}", "Nonce: ", "Issued At: ", "Expiration Time: "):
        assert field in message, field


def test_siwe_a_proven_wallet_signs_its_account_in(app, client, users):
    link_wallet(app)
    r = wallet_sign_in(client, WALLET, WALLET_KEY, next="/buyer/watchlist")
    assert r.status_code == 200 and r.get_json() == {"ok": True, "redirect": "/buyer/watchlist"}
    assert signed_in(client) and UserSession.query.filter_by(user_id=users["buyer"].id, revoked_at=None).count() == 1


def test_siwe_a_signature_from_another_key_signs_nobody_in(app, client, users):
    link_wallet(app)
    r = wallet_sign_in(client, WALLET, STRANGER_KEY)
    assert r.status_code == 403 and not signed_in(client)


def test_siwe_a_wallet_with_no_proven_account_is_told_how_to_link_it(app, client, users):
    r = wallet_sign_in(client, STRANGER, STRANGER_KEY)
    assert r.status_code == 404 and "link the wallet" in r.get_json()["error"] and not signed_in(client)
    users["seller"].wallet_address = STRANGER  # on record but never proven: still no
    db.session.commit()
    assert wallet_sign_in(client, STRANGER, STRANGER_KEY).status_code == 404


def test_siwe_each_message_works_once_and_expires(app, client, users):
    link_wallet(app)
    message = client.post("/auth/wallet-login/challenge", json={"address": WALLET}).get_json()["message"]
    signature = sign(message, WALLET_KEY)
    with client.session_transaction() as s:
        s["wallet_login"] = {**s["wallet_login"], "issued": int(time.time()) - 301}
    assert client.post("/auth/wallet-login/verify", json={"address": WALLET, "signature": signature}).status_code == 400
    assert client.post("/auth/wallet-login/verify", json={"address": WALLET, "signature": signature}).status_code == 400  # spent
    assert not signed_in(client)


def test_siwe_a_wallet_does_not_skip_two_step_sign_in(app, client, users):
    link_wallet(app)
    secret, _ = turn_on(client)
    r = wallet_sign_in(client, WALLET, WALLET_KEY)
    assert r.get_json()["redirect"] == "/auth/two-factor" and not signed_in(client)
    client.post("/auth/two-factor", data={"code": code(secret)})
    assert signed_in(client)


def test_siwe_a_deactivated_account_cannot_sign_in_with_its_wallet(app, client, users):
    link_wallet(app)
    users["buyer"].is_active_user = False
    db.session.commit()
    assert wallet_sign_in(client, WALLET, WALLET_KEY).status_code == 404


def test_siwe_the_login_page_offers_it_without_inline_code(client):
    html = client.get("/auth/login").get_data(as_text=True)
    assert 'id="wallet-login"' in html and "js/wallet-login.js" in html and "onclick" not in html
    assert "/auth/wallet-login/challenge" in html and "/auth/wallet-login/verify" in html


# =================================== Google sign-in ===========================================================================
class FakeGoogle:
    """Stands in for Authlib's Google client: hands back the claims a real, already-verified ID token would carry."""
    def __init__(self, claims=None, fail=False):
        self.claims, self.fail = claims, fail

    def authorize_redirect(self, redirect_uri):
        self.redirect_uri = redirect_uri
        return redirect("https://accounts.google.com/o/oauth2/v2/auth?client_id=test")

    def authorize_access_token(self):
        if self.fail:
            raise google_login.OAuthError(error="access_denied")
        return {"userinfo": self.claims}


def claims(email="gina@t.test", sub="google-sub-1", verified=True, name="Gina Google"):
    return {"sub": sub, "email": email, "email_verified": verified, "name": name}


@pytest.fixture
def google(app, monkeypatch):
    app.config.update(GOOGLE_CLIENT_ID="test-client.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET="test-secret")
    fake = FakeGoogle(claims())
    monkeypatch.setattr(google_login, "client", lambda: fake)
    return fake


def google_back(client, fake, **over):
    fake.claims = claims(**over)
    client.get("/auth/google")
    return client.get("/auth/google/callback?code=x&state=y")


def test_google_is_off_until_configured(client):
    assert client.get("/auth/google").status_code == 404 and client.get("/auth/google/callback").status_code == 404
    assert "Continue with Google" not in client.get("/auth/login").get_data(as_text=True)


def test_google_when_configured_the_button_starts_the_flow(client, google):
    for page in ("/auth/login", "/auth/register"):
        assert "Continue with Google" in client.get(page).get_data(as_text=True), page
    r = client.get("/auth/google")
    assert r.status_code == 302 and r.location.startswith("https://accounts.google.com/")
    assert google.redirect_uri.endswith("/auth/google/callback")


def test_google_a_new_person_finishes_signing_up_and_is_confirmed_at_once(client, google):
    r = google_back(client, google)
    assert r.status_code == 302 and r.location.endswith("/auth/google/finish")
    page = client.get("/auth/google/finish").get_data(as_text=True)
    assert "gina@t.test" in page and 'value="Gina Google"' in page
    r = client.post("/auth/google/finish", data={"name": "Gina Google", "phone": "9876543210", "address": "1 Main St",
                                                  "accept_terms": "y"})
    assert r.status_code == 302 and signed_in(client, "/seller/collectibles")
    user = User.query.filter_by(email="gina@t.test").one()
    assert user.google_sub == "google-sub-1" and user.email_verified and user.role == "member" and user.consent_version


def test_google_the_signup_still_needs_the_terms(client, google):
    google_back(client, google)
    r = client.post("/auth/google/finish", data={"name": "G", "phone": "9876543210", "address": "A", "role": "buyer"})
    assert r.status_code == 200 and b"You must agree to continue." in r.data and User.query.filter_by(email="gina@t.test").first() is None


def test_google_a_confirmed_account_with_that_email_is_linked_and_signed_in(client, google, users):
    r = google_back(client, google, email="buyer@t.test", sub="sub-buyer")
    assert r.status_code == 302 and r.location.endswith("/dashboard") and signed_in(client)
    assert db.session.get(User, users["buyer"].id).google_sub == "sub-buyer"
    client.post("/auth/logout")
    google_back(client, google, email="renamed@gmail.example", sub="sub-buyer")  # found by sub, even if the email changed
    assert signed_in(client)


def test_google_never_attaches_to_an_account_whose_email_is_unconfirmed(client, google, users):
    unverify(users["buyer"])
    r = google_back(client, google, email="buyer@t.test", sub="sub-attacker-target")
    assert r.location.endswith("/auth/login") and not signed_in(client)
    assert db.session.get(User, users["buyer"].id).google_sub is None


def test_google_an_address_google_has_not_confirmed_is_refused(client, google):
    r = google_back(client, google, verified=False)
    assert r.location.endswith("/auth/login") and User.query.filter_by(email="gina@t.test").first() is None


def test_google_a_cancelled_or_failed_sign_in_goes_back_to_login(client, google):
    google.fail = True
    client.get("/auth/google")
    r = client.get("/auth/google/callback?error=access_denied")
    assert r.status_code == 302 and r.location.endswith("/auth/login") and not signed_in(client)


def test_google_does_not_skip_two_step_sign_in(client, google, users):
    secret, _ = turn_on(client)
    r = google_back(client, google, email="buyer@t.test", sub="sub-buyer")
    assert r.location.endswith("/auth/two-factor") and not signed_in(client)
    client.post("/auth/two-factor", data={"code": code(secret)})
    assert signed_in(client)


def test_google_a_deactivated_account_stays_out(client, google, users):
    users["buyer"].is_active_user = False
    db.session.commit()
    r = google_back(client, google, email="buyer@t.test")
    assert r.location.endswith("/auth/login") and not signed_in(client)


def test_google_the_finish_page_needs_a_google_sign_in_first(client, google):
    assert client.get("/auth/google/finish").location.endswith("/auth/login")
    assert client.post("/auth/google/finish", data={"name": "x"}).location.endswith("/auth/login")


MIGRATION_GOOGLE = ROOT / "migrations" / "versions" / "n24google01_sign_in_with_google.py"


def test_google_the_migration_adds_a_unique_google_id():
    spec = importlib.util.spec_from_file_location("n24", MIGRATION_GOOGLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        conn.execute(sa.text("INSERT INTO users (google_sub) VALUES ('a')"))
        savepoint = conn.begin_nested()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("INSERT INTO users (google_sub) VALUES ('a')"))
        savepoint.rollback()
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert {c["name"] for c in sa.inspect(conn).get_columns("users")} == {"id"}
