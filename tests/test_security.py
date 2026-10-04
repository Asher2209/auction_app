import io
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from flask import g
from PIL import Image
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.config import TestConfig
from app.extensions import db, mail
from app.models import (
    Auction, Bid, Category, Feedback, Notification, Payment, Product, ProductImage, Review, User, Winner, utcnow,
)
from app.ratelimit import RateLimiter
from app.security import content_security_policy, production_problems

from .conftest import PASSWORD, login, make_user
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_payments import card, client_for, pay, won
from .test_seller import cat, form_data, img_bytes, post_new, seller  # noqa: F401  (fixtures)

TEMPLATES = os.path.join("app", "templates")


def anon(app):
    g.pop("_login_user", None)
    return app.test_client()


def bad_login(c, email="buyer@t.test", password="Wrong@1234", ip=None):
    kw = {"environ_overrides": {"REMOTE_ADDR": ip}} if ip else {}
    return c.post("/auth/login", data={"email": email, "password": password}, **kw)


# ============================ headers =================================================================
SEC_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "strict-origin-when-cross-origin",
               "Cross-Origin-Opener-Policy": "same-origin"}


@pytest.mark.parametrize("path", ["/", "/auctions/", "/auth/login", "/health", "/does-not-exist", "/static/css/style.css", "/verify/garbage"])
def test_security_headers_on_every_kind_of_response(app, path):
    r = anon(app).get(path)
    for name, value in SEC_HEADERS.items():
        assert r.headers.get(name) == value, (path, name)
    assert "camera=()" in r.headers["Permissions-Policy"] and "Content-Security-Policy" in r.headers


def test_headers_on_json_error_and_redirect_responses(app, users):
    c = client_for(app, "buyer@t.test")
    for r in (c.get("/admin/analytics/data"), c.post("/auctions/999/bid", data={"amount": "1"}, headers={"Accept": "application/json"}),
              anon(app).get("/buyer/")):
        assert r.headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_csp_forbids_inline_scripts_and_limits_sources(app):
    csp = anon(app).get("/").headers["Content-Security-Policy"]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert "'unsafe-inline'" not in directives["script-src"] and "'unsafe-eval'" not in directives["script-src"]
    assert set(directives["script-src"].split()) == {"'self'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"}
    assert directives["object-src"] == "'none'" and directives["base-uri"] == "'self'" and directives["form-action"] == "'self'"
    assert directives["frame-ancestors"] == "'none'" and directives["default-src"] == "'self'"
    assert "ws://localhost" in directives["connect-src"] and "wss://localhost" in directives["connect-src"]
    assert content_security_policy("example.com").count("example.com") == 2


def test_hsts_only_when_the_site_is_served_securely(app):
    assert "Strict-Transport-Security" not in anon(app).get("/").headers
    app.config["SESSION_COOKIE_SECURE"] = True
    assert "max-age=31536000" in anon(app).get("/").headers["Strict-Transport-Security"]


def test_pages_for_signed_in_users_are_not_cached(app, users):
    assert "no-store" in client_for(app, "buyer@t.test").get("/buyer/").headers["Cache-Control"]
    assert "no-store" not in anon(app).get("/").headers.get("Cache-Control", "")
    assert "no-store" not in client_for(app, "buyer@t.test").get("/static/css/style.css").headers.get("Cache-Control", "")


def test_no_inline_scripts_or_handlers_in_any_template():
    offenders = []
    for root, _, files in os.walk(TEMPLATES):
        for name in files:
            text = open(os.path.join(root, name), encoding="utf-8").read()
            for m in re.finditer(r"<script\b([^>]*)>", text, re.I):
                if "src=" not in m.group(1):
                    offenders.append((name, "inline <script>"))
            if re.search(r"\son(click|submit|change|load|error|input|focus|blur|mouse\w+|key\w+)\s*=", text, re.I):
                offenders.append((name, "inline event handler"))
            if re.search(r"""(href|src|action)\s*=\s*["']\s*javascript:""", text, re.I):
                offenders.append((name, "javascript: URL"))
    assert offenders == []


def test_every_third_party_asset_is_pinned_with_an_integrity_hash():
    seen = 0
    for root, _, files in os.walk(TEMPLATES):
        for name in files:
            for tag in re.findall(r"<(?:script|link)\b[^>]*>", open(os.path.join(root, name), encoding="utf-8").read()):
                m = re.search(r'(?:src|href)="(https?://[^"]+)"', tag)
                if m:
                    seen += 1
                    assert re.search(r'integrity="sha384-[A-Za-z0-9+/=]{64}"', tag) and 'crossorigin="anonymous"' in tag, (name, m.group(1))
                    assert m.group(1).startswith(("https://cdn.jsdelivr.net/", "https://cdnjs.cloudflare.com/")), m.group(1)
    assert seen >= 4


def test_rendered_pages_contain_no_inline_script_bodies(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Page", 10)
    pages = ["/", "/auctions/", f"/auctions/{a.id}", "/auth/login", "/auth/register"]
    admin = client_for(app, "admin@t.test")
    pages_admin = ["/admin/", "/admin/analytics", "/admin/reports", "/admin/reports/payments", "/admin/users", "/admin/reviews"]
    for c, paths in ((anon(app), pages), (admin, pages_admin)):
        for p in paths:
            html = c.get(p).data.decode()
            assert all("src=" in tag for tag in re.findall(r"<script\b[^>]*>", html)), p


def test_app_js_handles_confirm_and_autosubmit_without_inline_code(app):
    js = anon(app).get("/static/js/app.js").data.decode()
    assert "data-confirm" in js or "dataset.confirm" in js and "data-autosubmit" in js


# ============================ rate limiter (unit) ================================================================
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_limiter_sliding_window_and_retry_after():
    clock = Clock()
    lim = RateLimiter(clock)
    assert lim.retry_after("k", 3, 60) == 0
    for _ in range(3):
        lim.hit("k", 60)
        clock.t += 10
    assert lim.count("k", 60) == 3
    wait = lim.retry_after("k", 3, 60)
    assert 25 <= wait <= 32  # the first hit (30s ago) expires in 30s
    clock.t += wait
    assert lim.retry_after("k", 3, 60) == 0 and lim.count("k", 60) == 2
    clock.t += 1000
    assert lim.count("k", 60) == 0 and "k" not in lim._hits


def test_limiter_keys_are_independent_and_clearable():
    lim = RateLimiter(Clock())
    for _ in range(5):
        lim.hit("a", 60)
    assert lim.retry_after("a", 5, 60) > 0 and lim.retry_after("b", 5, 60) == 0
    lim.clear("a")
    assert lim.retry_after("a", 5, 60) == 0
    lim.clear("never-existed")


def test_limiter_is_thread_safe():
    lim = RateLimiter()
    ts = [threading.Thread(target=lambda: [lim.hit("k", 60) for _ in range(200)]) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert lim.count("k", 60) == 1600


def test_limiter_memory_is_bounded(monkeypatch):
    import app.ratelimit as rl
    monkeypatch.setattr(rl, "MAX_KEYS", 50)
    clock = Clock()
    lim = RateLimiter(clock)
    for i in range(60):
        lim.hit(f"old{i}", 10)
    clock.t += 100  # all of those have expired
    lim.hit("fresh", 10)
    assert len(lim._hits) == 1


# ============================ login throttling ======================================================================
def test_five_failures_lock_that_client_out_of_that_account(app, users):
    c = app.test_client()
    for _ in range(5):
        assert bad_login(c).status_code == 200
    r = bad_login(c)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0 and b"Too many attempts" in r.data
    r = bad_login(c, password=PASSWORD)  # the CORRECT password is refused too, and says nothing about being right
    assert r.status_code == 429 and b"Invalid" not in r.data
    g.pop("_login_user", None)
    assert c.get("/auth/profile").status_code == 302  # still not signed in


def test_lockout_ends_when_the_window_passes(app, users):
    clock = Clock()
    app.extensions["limiter"]._clock = clock
    c = app.test_client()
    for _ in range(5):
        bad_login(c)
    assert bad_login(c, password=PASSWORD).status_code == 429
    clock.t += 901
    assert bad_login(c, password=PASSWORD).status_code == 302


def test_other_accounts_and_other_clients_are_unaffected_by_one_lockout(app, users):
    c = app.test_client()
    for _ in range(5):
        bad_login(c)
    assert bad_login(c).status_code == 429
    assert bad_login(c, email="seller@t.test", password=PASSWORD).status_code == 302  # a different account
    g.pop("_login_user", None)
    assert bad_login(app.test_client(), password=PASSWORD, ip="10.9.9.9").status_code == 302  # same account, another client


def test_a_successful_login_resets_the_counter(app, users):
    c = app.test_client()
    for _ in range(4):
        bad_login(c)
    assert bad_login(c, password=PASSWORD).status_code == 302
    c.post("/auth/logout")
    g.pop("_login_user", None)
    for _ in range(4):
        assert bad_login(c).status_code == 200  # a fresh allowance: not blocked after 4 more failures
    assert bad_login(c, password=PASSWORD).status_code == 302


def test_unknown_emails_are_throttled_exactly_like_real_ones(app, users):
    """If real accounts locked sooner than made-up ones, the lockout would reveal which accounts exist."""
    c = app.test_client()
    codes = [bad_login(c, email="ghost@t.test").status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


def test_one_client_trying_many_accounts_is_stopped_at_twenty(app, users):
    c = app.test_client()
    for i in range(20):
        assert bad_login(c, email=f"user{i}@t.test").status_code == 200
    assert bad_login(c, email="fresh@t.test").status_code == 429
    assert bad_login(c, email="fresh@t.test", ip="10.2.2.2").status_code == 200  # other clients are fine


def test_many_clients_against_one_account_are_stopped_at_thirty(app, users):
    c = app.test_client()
    for i in range(30):
        assert bad_login(c, ip=f"10.1.{i // 250}.{i % 250 + 1}").status_code == 200
    assert bad_login(c, password=PASSWORD, ip="10.7.7.7").status_code == 429


def test_login_throttle_counts_the_email_case_insensitively(app, users):
    c = app.test_client()
    for e in ("Buyer@T.test", "BUYER@t.test", "buyer@T.TEST", "buyer@t.test", "BuYeR@t.test"):
        bad_login(c, email=e)
    assert bad_login(c, email="buyer@t.test").status_code == 429


# ============================ other throttles ========================================================================
def test_forgot_password_is_limited_per_client_and_per_address(app, users):
    c = app.test_client()
    with mail.record_messages() as outbox:
        for _ in range(3):
            assert c.post("/auth/forgot-password", data={"email": "buyer@t.test"}).status_code == 302
        for _ in range(2):  # the 4th and 5th reply the same but no further emails go to that address
            assert c.post("/auth/forgot-password", data={"email": "buyer@t.test"}, follow_redirects=True).status_code == 200
    assert len(outbox) == 3
    assert c.post("/auth/forgot-password", data={"email": "other@t.test"}).status_code == 429  # 6th from this client
    assert anon(app).post("/auth/forgot-password", data={"email": "other@t.test"}, environ_overrides={"REMOTE_ADDR": "10.3.3.3"}).status_code == 302


def test_registration_is_limited_per_client(app):
    c = app.test_client()
    base = {"name": "N", "phone": "9876543210", "address": "A", "role": "buyer", "password": "Passw0rdX", "confirm": "Passw0rdX"}
    codes = [c.post("/auth/register", data={**base, "email": f"n{i}@t.test"}).status_code for i in range(11)]
    assert codes[:10] == [302] * 10 and codes[10] == 429
    assert c.get("/auth/register").status_code == 200  # only submissions are counted, not page views


def test_bidding_is_limited_per_user_and_answers_json(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Spam target", 100)
    c = client_for(app, "buyer@t.test")
    headers = {"Accept": "application/json"}
    for _ in range(30):
        assert c.post(f"/auctions/{a.id}/bid", data={"amount": "abc"}, headers=headers).status_code == 400
    r = c.post(f"/auctions/{a.id}/bid", data={"amount": "150"}, headers=headers)
    assert r.status_code == 429 and r.get_json()["ok"] is False and int(r.headers["Retry-After"]) > 0
    assert Bid.query.count() == 0
    other = make_user("b2@t.test")
    assert client_for(app, "b2@t.test").post(f"/auctions/{a.id}/bid", data={"amount": "150"}, headers=headers).status_code == 200


def test_payment_attempts_are_limited_per_user(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    codes = [pay(c, a, "card", card(cvv="xx")).status_code for _ in range(21)]
    assert codes[:20] == [400] * 20 and codes[20] == 429


# ============================ sessions and cookies ======================================================================
def test_login_cookie_flags_and_it_is_a_browser_session_cookie(app, users):
    c = app.test_client()
    bad_login(c, password=PASSWORD)
    cookie = c.get_cookie("session")
    assert cookie.http_only and cookie.same_site == "Lax"
    assert cookie.expires is None  # a permanent cookie would switch off Flask-Login's strong session protection


def set_login_age(client, seconds):
    with client.session_transaction() as sess:
        sess["login_at"] = int(time.time()) - seconds


def test_logins_end_after_eight_hours_on_the_server(app, users):
    c = client_for(app, "buyer@t.test")
    set_login_age(c, 7 * 3600 + 3000)
    g.pop("_login_user", None)
    assert c.get("/buyer/").status_code == 200  # just under 8 hours: still signed in
    set_login_age(c, 8 * 3600 + 5)
    g.pop("_login_user", None)
    assert c.get("/buyer/").status_code == 302  # over: signed out
    g.pop("_login_user", None)
    assert c.get("/buyer/").status_code == 302  # and it stays ended


def test_forged_or_old_sessions_without_a_valid_start_time_are_rejected(app, users):
    for bad in (None, "yesterday", 1.5, [1], True and "1"):
        c = client_for(app, "buyer@t.test")
        with c.session_transaction() as sess:
            if bad is None:
                sess.pop("login_at")
            else:
                sess["login_at"] = bad
        g.pop("_login_user", None)
        assert c.get("/buyer/").status_code == 302, bad


def test_secure_flag_is_set_when_configured():
    class Secure(TestConfig):
        SESSION_COOKIE_SECURE = True

    app = create_app(Secure)
    with app.app_context():
        db.create_all()
        make_user("buyer@t.test")
        c = app.test_client()
        c.post("/auth/login", data={"email": "buyer@t.test", "password": PASSWORD}, base_url="https://localhost")
        assert c.get_cookie("session", domain="localhost").secure
        db.drop_all()


def test_a_session_used_from_a_different_browser_is_dropped(app, users):
    c = client_for(app, "buyer@t.test")
    assert c.get("/auth/profile").status_code == 200
    g.pop("_login_user", None)
    assert c.get("/auth/profile", headers={"User-Agent": "Totally Different Browser/1.0"}).status_code == 302


def test_logout_really_ends_the_session(app, users):
    c = client_for(app, "buyer@t.test")
    c.post("/auth/logout")
    g.pop("_login_user", None)
    assert c.get("/buyer/").status_code == 302


def test_passwords_are_salted_and_slow_hashed(app):
    a, b = User(name="a", email="a@t.test"), User(name="b", email="b@t.test")
    a.set_password("SamePassw0rd"), b.set_password("SamePassw0rd")
    assert a.password_hash != b.password_hash and a.password_hash.split(":")[0] in ("scrypt", "pbkdf2") and "SamePassw0rd" not in a.password_hash


def test_passwords_never_reach_the_logs(app, users, caplog):
    secret = "S3cret-Pa55word-Marker"
    with caplog.at_level(logging.DEBUG):
        c = app.test_client()
        bad_login(c, password=secret)
        c.post("/auth/register", data={"name": "N", "email": "n@t.test", "phone": "9876543210", "address": "A", "role": "buyer", "password": secret, "confirm": secret})
        c.post("/auth/forgot-password", data={"email": "buyer@t.test"})
    assert secret not in caplog.text


# ============================ production configuration ==================================================================
def prod(**over):
    class Prod(TestConfig):
        APP_ENV = "production"
        SECRET_KEY = "k" * 48
        SESSION_COOKIE_SECURE = True
        ALLOW_TEST_EMAILS = False
        LOCAL_CHAIN = False
        APP_BASE_URL = "https://auction.example.org"

    for k, v in over.items():
        setattr(Prod, k, v)
    return Prod


def test_a_correct_production_config_starts():
    assert production_problems(create_app(prod())) == []


@pytest.mark.parametrize("over,phrase", [
    ({"SECRET_KEY": "dev-only-secret"}, "SECRET_KEY"), ({"SECRET_KEY": "short"}, "SECRET_KEY"), ({"SECRET_KEY": "change-me"}, "SECRET_KEY"),
    ({"SESSION_COOKIE_SECURE": False}, "SECURE_COOKIES"), ({"ALLOW_TEST_EMAILS": True}, "ALLOW_TEST_EMAILS"),
    ({"APP_BASE_URL": "http://insecure.example"}, "https://"), ({"APP_BASE_URL": "http://127.0.0.1:5000"}, "https://"),
])
def test_each_unsafe_production_setting_stops_the_app(over, phrase):
    with pytest.raises(RuntimeError) as e:
        create_app(prod(**over))
    assert "Unsafe production configuration" in str(e.value) and phrase in str(e.value)


def test_all_problems_are_reported_together():
    class Bad(TestConfig):
        APP_ENV = "production"
        ALLOW_TEST_EMAILS = True

    with pytest.raises(RuntimeError) as e:
        create_app(Bad)
    msg = str(e.value)
    assert all(p in msg for p in ("SECRET_KEY", "SECURE_COOKIES", "ALLOW_TEST_EMAILS", "https://"))


def test_development_config_is_not_blocked():
    assert create_app(TestConfig).config["APP_ENV"] == "development"


def test_production_never_logs_email_bodies(app, users, caplog):
    app.testing = False
    app.config.update(APP_ENV="production", MAIL_SERVER=None)
    try:
        with caplog.at_level(logging.INFO):
            from app.services.mailer import send_email
            send_email("x@t.test", "Reset", "Use this link: https://site/reset/SECRET-TOKEN")
    finally:
        app.testing = True
    assert "SECRET-TOKEN" not in caplog.text and "skipped" in caplog.text


# ============================ errors never leak ===========================================================================
def boom_app():
    class Quiet(TestConfig):
        PROPAGATE_EXCEPTIONS = False

    app = create_app(Quiet)

    @app.route("/boom")
    def boom():
        raise RuntimeError("SELECT * FROM users WHERE password='hunter2' at C:\\secret\\path.py")

    @app.route("/boom-json")
    def boom_json():
        raise ValueError("db password is hunter2")

    return app


def test_unhandled_errors_show_a_generic_page(caplog):
    app = boom_app()
    with caplog.at_level(logging.CRITICAL):
        r = app.test_client().get("/boom")
    body = r.data.decode()
    assert r.status_code == 500 and "Something went wrong" in body
    for leak in ("hunter2", "SELECT", "Traceback", "secret", "RuntimeError", "path.py"):
        assert leak not in body


def test_api_style_errors_are_json_without_details(caplog):
    app = boom_app()
    with caplog.at_level(logging.CRITICAL):
        r = app.test_client().get("/boom-json", headers={"Accept": "application/json"})
    assert r.status_code == 500 and r.get_json() == {"ok": False, "error": "Something went wrong on our side. Please try again."}
    assert "hunter2" not in r.get_data(as_text=True)


def test_friendly_error_pages(app, users):
    c = client_for(app, "buyer@t.test")
    assert b"Page not found" in c.get("/nope").data
    assert b"not allowed" in c.post("/health").data and c.post("/health").status_code == 405
    assert b"permission" in c.get("/admin/").data and c.get("/admin/").status_code == 403


def test_csrf_failure_is_a_friendly_400():
    class Strict(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(Strict)
    with app.app_context():
        r = app.test_client().post("/auth/login", data={"email": "a@t.test", "password": "x"})
        assert r.status_code == 400 and b"session expired" in r.data and b"Traceback" not in r.data
        j = app.test_client().post("/auth/login", data={}, headers={"Accept": "application/json"})
        assert j.status_code == 400 and j.get_json()["ok"] is False


def test_oversized_requests_are_refused(app, client, seller, cat):  # noqa: F811
    app.config["MAX_CONTENT_LENGTH"] = 2000
    r = seller_post(client, cat, images=[(io.BytesIO(b"x" * 5000), "a.png")])
    assert r.status_code == 413 and b"too large" in r.data.lower() and Product.query.count() == 0


def seller_post(client, category, **over):
    return client.post("/seller/products/new", data=form_data(category, **over), content_type="multipart/form-data")


# ============================ database integrity ==========================================================================
def test_foreign_keys_are_enforced_by_the_database(app, users):
    db.session.add(Bid(auction_id=9999, buyer_id=users["buyer"].id, amount=Decimal(5)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_unique_rules_hold_at_the_database_level(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "U", 10)
    db.session.add(Review(product_id=a.product_id, buyer_id=users["buyer"].id, rating=5))
    db.session.commit()
    db.session.add(Review(product_id=a.product_id, buyer_id=users["buyer"].id, rating=1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(User(name="dup", email="buyer@t.test", password_hash="x"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# ============================ default deny and roles =======================================================================
PUBLIC = {"main.index", "main.health", "auctions.browse", "auctions.detail", "auctions.state", "auth.login", "auth.register",
          "auth.forgot_password", "auth.reset_password", "invoices.verify", "static"}
FILL = {"integer": 1, "string": "x", "path": "x", "uuid": "00000000-0000-0000-0000-000000000000"}


def url_for_rule(rule):
    path = rule.rule
    for arg, conv in rule._converters.items():
        name = conv.__class__.__name__.lower().replace("converter", "")
        value = re.sub(r"[()?:]", "", conv.regex).split("|")[0] if name == "any" else FILL.get(name, "x")
        path = re.sub(rf"<[^<>]*\b{arg}>", str(value), path)
    return path


def rules(app, prefix=None):
    return [r for r in app.url_map.iter_rules() if prefix is None or r.endpoint.startswith(prefix)]


def test_every_non_public_route_refuses_anonymous_visitors(app):
    c = anon(app)
    checked = 0
    for rule in rules(app):
        if rule.endpoint in PUBLIC or rule.endpoint.startswith("devwallet"):
            continue
        for method in sorted(rule.methods & {"GET", "POST"}):
            r = c.open(url_for_rule(rule), method=method)
            assert r.status_code in (301, 302, 303, 307, 308, 400, 401, 403, 404, 405), (rule.endpoint, method, r.status_code)
            assert r.status_code != 200, (rule.endpoint, method)
            checked += 1
    expected = sum(len(r.methods & {'GET', 'POST'}) for r in rules(app) if r.endpoint not in PUBLIC and not r.endpoint.startswith('devwallet'))
    assert checked == expected >= 50  # every method of every non-public route was tried


def test_public_routes_never_return_server_errors_for_garbage(app):
    c = anon(app)
    for rule in rules(app):
        if rule.endpoint in PUBLIC and rule.endpoint != "static":
            for method in sorted(rule.methods & {"GET", "POST"}):
                assert c.open(url_for_rule(rule), method=method).status_code < 500, (rule.endpoint, method)


ROLE_PREFIXES = {"admin.": "admin", "seller.": "seller", "buyer.": "buyer", "payments.": "buyer", "reviews.": "buyer"}


@pytest.mark.parametrize("prefix,owner", ROLE_PREFIXES.items())
def test_each_area_refuses_every_other_role(app, users, prefix, owner):
    others = [r for r in ("buyer", "seller", "admin") if r != owner]
    for role in others:
        c = client_for(app, f"{role}@t.test")
        for rule in rules(app, prefix):
            for method in sorted(rule.methods & {"GET", "POST"}):
                r = c.open(url_for_rule(rule), method=method)
                assert r.status_code == 403, (role, rule.endpoint, method, r.status_code)


MUTATING_WORDS = ("delete", "hide", "unhide", "approve", "reject", "remove", "toggle", "mark", "place_bid", "save", "submit", "prepare",
                  "rename", "logout", "pay", "send", "mine", "create", "edit")
VIEWS = {"payments.pay_page", "seller.create_product", "seller.edit_product", "buyer.watchlist"}  # show a page; changes need POST
GET_EXCEPTIONS = {"notifications.go"}  # opening a notification marks it read, then redirects: harmless and ownership-checked


def test_state_changing_endpoints_do_not_accept_get(app):
    offenders = []
    for rule in rules(app):
        name = rule.endpoint.split(".")[-1]
        if "GET" in rule.methods and any(name == w or name.startswith(w + "_") for w in MUTATING_WORDS) and rule.endpoint not in GET_EXCEPTIONS | VIEWS:
            if rule.methods & {"POST"}:
                continue  # form pages that show a form on GET and change state only on POST
            offenders.append(rule.endpoint)
    assert offenders == []


# ============================ ownership (IDOR) ===============================================================================
@pytest.fixture
def two_sides(app, users, cats):  # noqa: F811
    """Seller A + buyer A with a paid auction, a review and a notification; plus an unrelated seller B and buyer B."""
    a = won(users, cats, amount="500")
    pay(client_for(app, "buyer@t.test"), a, "card", card())
    n = Notification.query.filter_by(user_id=users["buyer"].id).first()
    db.session.add(Review(product_id=a.product_id, buyer_id=users["buyer"].id, rating=4, comment="mine"))
    make_user("sellerb@t.test", "seller")
    make_user("buyerb@t.test")
    hidden = make_auction(users["seller"], cats["Sports"], "Hidden", 10, status="cancelled")
    db.session.commit()
    return a, n, hidden


def test_another_buyer_cannot_reach_someone_elses_payment_data(app, two_sides):
    a, n, hidden = two_sides
    c = client_for(app, "buyerb@t.test")
    before = Payment.query.one().payment_status
    for method, path in (("GET", f"/payments/{a.id}"), ("GET", f"/payments/{a.id}/status"), ("POST", f"/payments/{a.id}/pay/card"),
                         ("POST", f"/payments/{a.id}/crypto/prepare"), ("POST", f"/payments/{a.id}/crypto/submit"),
                         ("GET", f"/invoices/{a.id}/download")):
        assert c.open(path, method=method, data=card(), json=None if method == "GET" else None).status_code in (404,), path
    assert Payment.query.one().payment_status == before


def test_another_seller_cannot_touch_the_product_or_invoice(app, two_sides):
    a, n, hidden = two_sides
    c = client_for(app, "sellerb@t.test")
    for method, path in (("GET", f"/seller/products/{a.product_id}"), ("GET", f"/seller/products/{a.product_id}/edit"),
                         ("POST", f"/seller/products/{a.product_id}/edit"), ("POST", f"/seller/products/{a.product_id}/delete"),
                         ("GET", f"/invoices/{a.id}/download")):
        assert c.open(path, method=method).status_code == 404, path
    assert Product.query.filter_by(id=a.product_id).count() == 1


def test_another_buyer_cannot_review_delete_or_read_notifications_of_others(app, two_sides, users):
    a, n, hidden = two_sides
    c = client_for(app, "buyerb@t.test")
    c.post(f"/reviews/{a.id}", data={"rating": "1", "comment": "hijack"})
    c.post(f"/reviews/{a.id}/delete")
    rv = Review.query.one()
    assert rv.buyer_id == users["buyer"].id and rv.comment == "mine" and rv.rating == 4
    for method, path in (("POST", f"/notifications/{n.id}/read"), ("GET", f"/notifications/{n.id}/go")):
        assert c.open(path, method=method).status_code == 404
    db.session.refresh(n)
    assert n.is_read is False


def test_hidden_listings_cannot_be_watched_or_viewed(app, two_sides):
    a, n, hidden = two_sides
    c = client_for(app, "buyerb@t.test")
    assert c.post(f"/buyer/watchlist/{hidden.id}/toggle").status_code == 404
    assert c.get(f"/auctions/{hidden.id}").status_code == 404


def test_notifications_page_lists_only_the_owners_items(app, two_sides, users):
    a, n, hidden = two_sides
    other = client_for(app, "buyerb@t.test").get("/notifications/").data.decode()
    assert "Auction won" not in other and "Payment successful" not in other


# ============================ injection and XSS ================================================================================
SQLI = ["' OR '1'='1", "'; DROP TABLE users;--", '" OR ""="', "1; SELECT sleep(5)", "%", "_", "\\", "' UNION SELECT password_hash,2,3,4 FROM users--",
        "a" * 3000, "\u202e<>\u0000", "0x27 OR 1=1", "'||(SELECT password_hash FROM users)||'", "1' AND (SELECT COUNT(*) FROM users)>0 --"]


@pytest.mark.parametrize("payload", SQLI)
def test_sql_injection_corpus_on_public_and_admin_search(app, users, cats, payload):  # noqa: F811
    make_auction(users["seller"], cats["Books"], "Normal item", 100)
    users_before = User.query.count()
    admin = client_for(app, "admin@t.test")
    urls = [("anon", "/auctions/", {"q": payload, "category": payload, "min_price": payload, "max_price": payload, "status": payload,
                                    "sort": payload, "page": payload}),
            ("admin", "/admin/products", {"q": payload, "status": payload}), ("admin", "/admin/users", {"q": payload, "role": payload}),
            ("admin", "/admin/reviews", {"q": payload, "status": payload}), ("admin", "/admin/feedback", {"q": payload}),
            ("admin", "/admin/reports/payments", {"from": payload, "to": payload, "status": payload}),
            ("admin", "/admin/reports/daily-auctions", {"day": payload}), ("admin", "/admin/analytics/data", {"months": payload}),
            ("admin", "/notifications/", {"filter": payload}), ("admin", "/admin/", {"x": payload})]
    for who, path, params in urls:
        c = anon(app) if who == "anon" else admin
        r = c.get(path, query_string=params)
        assert r.status_code < 500, (path, payload)
        assert b"scrypt:" not in r.data and b"pbkdf2:" not in r.data, (path, payload)  # no hash value ever shown
    assert User.query.count() == users_before


@pytest.mark.parametrize("payload", SQLI)
def test_sql_injection_corpus_on_login_and_forms(app, users, payload):
    c = anon(app)
    assert bad_login(c, email=payload, password=payload).status_code in (200, 429)
    r = c.post("/auth/forgot-password", data={"email": payload})
    assert r.status_code in (200, 302, 429)
    assert User.query.count() == 3 and db.session.get(User, users["buyer"].id).check_password(PASSWORD)


XSS = ["<script>alert(1)</script>", '"><img src=x onerror=alert(1)>', "'-alert(1)-'", "<svg/onload=alert(1)>", "{{7*7}}", "{% raw %}{% endraw %}",
       "${7*7}", "javascript:alert(1)", "</textarea><script>alert(2)</script>", "<iframe src=//evil.example>"]


@pytest.mark.parametrize("payload", XSS)
def test_stored_text_is_escaped_on_every_page_that_shows_it(app, users, cats, payload):  # noqa: F811
    seller, buyer = users["seller"], users["buyer"]
    seller.name = payload[:100]
    buyer.name, buyer.address = payload[:100], payload
    cats["Books"].name = payload[:75]
    a = make_auction(seller, cats["Books"], payload[:190], 100, desc=payload)
    a.product.rejection_reason = payload
    db.session.add_all([Review(product_id=a.product_id, buyer_id=buyer.id, rating=5, comment=payload),
                        Feedback(user_id=buyer.id, message=payload),
                        Notification(user_id=buyer.id, title=payload[:140], message=payload, url="/auctions/")])
    db.session.commit()
    pages = [(anon(app), p) for p in ("/", "/auctions/", f"/auctions/{a.id}", f"/auctions/?q=x&category={cats['Books'].id}")]
    pages += [(client_for(app, "buyer@t.test"), p) for p in ("/notifications/", "/buyer/", "/buyer/bids", "/auth/profile", "/feedback")]
    pages += [(client_for(app, "seller@t.test"), p) for p in ("/seller/", f"/seller/products/{a.product_id}", "/seller/reviews")]
    pages += [(client_for(app, "admin@t.test"), p) for p in ("/admin/products?status=all", f"/admin/products/{a.product_id}", "/admin/users",
                                                          "/admin/categories", "/admin/reviews", "/admin/feedback", "/admin/reports/top-products?from=2000-01-01")]
    for c, path in pages:
        g.pop("_login_user", None)  # these clients were all created up front; do not let one actor's cached login leak into the next
        r = c.get(path)
        assert r.status_code == 200, path
        html = r.data.decode()
        if "<" in payload:
            assert payload not in html, (path, "unescaped")
        if payload == "{{7*7}}":
            assert ">49<" not in html and " 49 " not in html.replace("\n", " ").split("<main")[-1], path  # not evaluated as a template
        if payload == "${7*7}":
            assert ">49<" not in html, path


def test_user_text_in_attributes_cannot_break_out(app, users, cats):  # noqa: F811
    payload = '" onfocus="alert(1)" autofocus x="'
    a = make_auction(users["seller"], cats["Books"], "Attr", 100)
    c = client_for(app, "admin@t.test")
    html = c.get(f"/admin/users?q={payload}").data.decode()
    assert 'onfocus="alert(1)"' not in html and "&#34;" in html
    html = c.get(f"/admin/reports/payments?status={payload}").data.decode()
    assert 'onfocus="alert(1)"' not in html


# ============================ uploads ===========================================================================================
def png(size=(10, 10)):
    return img_bytes("PNG", size)


def test_filenames_cannot_escape_the_upload_folder(app, client, seller, cat):  # noqa: F811
    for name in ("../../evil.png", "..\\..\\evil.png", "/etc/passwd.png", "a/b/c.png", "shell.php.png", "x" * 300 + ".png", "na\u00efve \u65e5\u672c.png"):
        r = seller_post(client, cat, images=[(png(), name)])
        assert r.status_code == 302, name
    root = app.config["UPLOAD_FOLDER"]
    stored = [i.path for i in ProductImage.query.all()]
    assert len(stored) == 7 and all(re.fullmatch(r"products/[0-9a-f]{32}\.png", p) for p in stored)  # names are random, never the user's
    inside = set(os.listdir(os.path.join(root, "products")))
    assert inside == {os.path.basename(p) for p in stored}
    assert not os.path.exists(os.path.join(root, "..", "evil.png")) and not os.path.exists(os.path.join(os.path.dirname(root), "evil.png"))


@pytest.mark.parametrize("name,data", [
    ("shell.php", png().getvalue()), ("x.png.php", png().getvalue()), ("x.svg", b"<svg onload=alert(1)></svg>"), ("x.png", b"<svg onload=alert(1)></svg>"),
    ("x.png", b"<?php system($_GET['c']); ?>"), ("x.gif", b"GIF89a" + b"<?php system($_GET['c']); ?>"), ("x.html", b"<script>alert(1)</script>"),
    ("x.png\x00.php", png().getvalue()), ("x.jpg", b""), ("x.png", b"\x89PNG\r\n\x1a\n" + b"junk"), ("x.exe", b"MZ\x90\x00"), ("noextension", png().getvalue()),
    ("x.bmp", img_bytes("BMP").getvalue()), ("x.tiff", img_bytes("TIFF").getvalue()), ("x.ico", img_bytes("ICO").getvalue()),
])
def test_dangerous_or_fake_uploads_are_rejected(app, client, seller, cat, name, data):  # noqa: F811
    r = seller_post(client, cat, images=[(io.BytesIO(data), name)])
    assert r.status_code == 200 and Product.query.count() == 0 and ProductImage.query.count() == 0
    folder = os.path.join(app.config["UPLOAD_FOLDER"], "products")
    assert not os.path.exists(folder) or os.listdir(folder) == []


def test_decompression_bombs_are_rejected(app, client, seller, cat):  # noqa: F811
    big = io.BytesIO()
    Image.new("1", (9000, 9000)).save(big, "PNG")  # 81 million pixels, a few KB on disk
    big.seek(0)
    assert big.getbuffer().nbytes < 200_000
    r = seller_post(client, cat, images=[(big, "bomb.png")])
    assert r.status_code == 200 and b"too large" in r.data.lower() and Product.query.count() == 0


def test_static_files_are_served_as_what_they_are_and_cannot_be_sniffed(app):
    """Uploads are saved under static/uploads, so this is how an uploaded image is served."""
    folder = os.path.join(app.static_folder, "uploads")
    probe = os.path.join(folder, "zz_security_probe.png")
    with open(probe, "wb") as f:
        f.write(png().getvalue())
    try:
        r = anon(app).get("/static/uploads/zz_security_probe.png")
        assert r.status_code == 200 and r.mimetype == "image/png" and r.headers["X-Content-Type-Options"] == "nosniff"
        r.close()  # release the file (Windows will not delete a file that is still open)
    finally:
        os.remove(probe)
    for evil in ("/static/uploads/products/../../../config.py", "/static/%2e%2e/%2e%2e/.env", "/static/..%2f..%2fconfig.py", "/static/uploads/../../__init__.py"):
        assert anon(app).get(evil).status_code == 404, evil


def test_too_many_images_in_one_request_are_refused(app, client, seller, cat):  # noqa: F811
    r = seller_post(client, cat, images=[(png(), f"{i}.png") for i in range(6)])
    assert r.status_code == 200 and Product.query.count() == 0 and ProductImage.query.count() == 0


# ============================ mass assignment, redirects ========================================================================
def test_clients_cannot_set_fields_they_should_not(app, client, seller, cat, users):  # noqa: F811
    seller_post(client, cat, **{"approval_status": "approved", "seller_id": str(users["admin"].id), "rejection_reason": "x", "id": "999", "is_hidden": "1"})
    p = Product.query.one()
    assert p.approval_status == "pending" and p.seller_id == users["seller"].id and p.rejection_reason is None and p.id != 999


def test_registration_cannot_grant_privileges(app):
    base = {"name": "N", "email": "n@t.test", "phone": "9876543210", "address": "A", "role": "buyer", "password": "Passw0rdX", "confirm": "Passw0rdX"}
    anon(app).post("/auth/register", data={**base, "is_active_user": "0", "wallet_address": "0x" + "1" * 40, "id": "77", "created_at": "2000-01-01", "role": "buyer"})
    u = User.query.filter_by(email="n@t.test").one()
    assert u.role == "buyer" and u.is_active_user and u.wallet_address is None and u.id != 77 and u.created_at.year > 2000
    r = anon(app).post("/auth/register", data={**base, "email": "adm@t.test", "role": "admin"})
    assert r.status_code == 200 and User.query.filter_by(email="adm@t.test").count() == 0


UNSAFE_TARGETS = ["https://evil.example/", "//evil.example", "///evil.example", "http:evil.example", "https:evil.example", "javascript:alert(1)",
                  "\\\\evil.example", "/\\evil.example", "https:/evil.example", "data:text/html,x", "/ok\r\nSet-Cookie: x=1", "http://evil.example@localhost/",
                  "http://localhost.evil.example/", "  //evil.example", "/" + "a" * 3000]


@pytest.mark.parametrize("target", range(len(UNSAFE_TARGETS)))
def test_open_redirect_corpus_on_login(app, users, target):
    r = anon(app).post("/auth/login", query_string={"next": UNSAFE_TARGETS[target]}, data={"email": "buyer@t.test", "password": PASSWORD})
    assert r.status_code == 302 and r.location == "/dashboard"  # every unsafe target is replaced by the safe default


def test_safe_redirect_targets_still_work(app, users):
    for given, expected in (("/auth/profile", "/auth/profile"), ("/auctions/?q=lamp&page=2", "/auctions/?q=lamp&page=2"),
                            ("http://localhost/auth/profile?x=1", "/auth/profile?x=1")):
        r = anon(app).post("/auth/login", query_string={"next": given}, data={"email": "buyer@t.test", "password": PASSWORD})
        assert r.location == expected, given


def test_safe_redirect_target_unit(app):
    from app.utils import safe_redirect_target
    with app.test_request_context("/"):
        assert safe_redirect_target("/a/b?c=d") == "/a/b?c=d" and safe_redirect_target("http://localhost/a?b=1") == "/a?b=1"
        for bad in (None, "", 5, "a/b", "//x", "http://other/", "https://localhost.evil/", "javascript:1", "/a\\b", "/a\nb"):
            assert safe_redirect_target(bad) is None, bad


def test_referer_based_redirects_ignore_foreign_origins(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Ref", 10)
    c = client_for(app, "buyer@t.test")
    r = c.post(f"/buyer/watchlist/{a.id}/toggle", headers={"Referer": "http://evil.example/steal"})
    assert r.location == f"/auctions/{a.id}"
    r = c.post(f"/buyer/watchlist/{a.id}/toggle", headers={"Referer": "http://localhost/auctions/?q=x"})
    assert r.location == "/auctions/?q=x"
