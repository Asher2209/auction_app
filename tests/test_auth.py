import re

from app import create_app
from app.blueprints.auth.tokens import make_reset_token
from app.config import TestConfig
from app.extensions import db
from app.models import User

from .conftest import PASSWORD, login, make_user

REG = {
    "name": "New User", "email": "new@t.test", "phone": "9876543210",
    "address": "1 Main St", "role": "buyer", "password": "Passw0rdX", "confirm": "Passw0rdX",
}


# ---- registration -------------------------------------------------------
def test_register_success_hashes_password(client):
    r = client.post("/auth/register", data=REG)
    assert r.status_code == 302
    u = User.query.filter_by(email="new@t.test").one()
    assert u.role == "buyer" and u.password_hash != REG["password"]


def test_register_email_normalised_and_duplicate_rejected(client):
    client.post("/auth/register", data={**REG, "email": "Dup@T.test"})
    r = client.post("/auth/register", data={**REG, "email": "dup@t.test"})
    assert r.status_code == 200 and b"already exists" in r.data
    assert User.query.count() == 1


def test_register_cannot_choose_admin_role(client):
    r = client.post("/auth/register", data={**REG, "role": "admin"})
    assert r.status_code == 200
    assert User.query.count() == 0


def test_register_weak_password_and_mismatch(client):
    for pw, confirm in [("short1", "short1"), ("allletters", "allletters"), ("Passw0rdX", "Different1")]:
        r = client.post("/auth/register", data={**REG, "password": pw, "confirm": confirm})
        assert r.status_code == 200
    assert User.query.count() == 0


def test_register_bad_phone_and_email(client):
    assert client.post("/auth/register", data={**REG, "phone": "abc"}).status_code == 200
    assert client.post("/auth/register", data={**REG, "email": "nope"}).status_code == 200
    assert User.query.count() == 0


# ---- login / logout -----------------------------------------------------
def test_login_logout_flow(client, users):
    r = login(client, "buyer@t.test")
    assert r.status_code == 302 and r.location.endswith("/dashboard")
    assert client.get("/auth/profile").status_code == 200
    assert client.post("/auth/logout").status_code == 302
    assert client.get("/auth/profile").status_code == 302  # redirected to login


def test_login_failures_share_one_message(client, users):
    a = login(client, "buyer@t.test", "Wrong@1234")
    b = login(client, "ghost@t.test")
    assert b"Invalid email or password" in a.data and b"Invalid email or password" in b.data


def test_inactive_user_cannot_login(client):
    make_user("off@t.test", active=False)
    assert b"Invalid email or password" in login(client, "off@t.test").data


def test_login_next_open_redirect_blocked(client, users):
    r = client.post("/auth/login?next=https://evil.example/", data={"email": "buyer@t.test", "password": PASSWORD})
    assert r.location.endswith("/dashboard")
    client.post("/auth/logout")
    r = client.post("/auth/login?next=/auth/profile", data={"email": "buyer@t.test", "password": PASSWORD})
    assert r.location.endswith("/auth/profile")


def test_logout_requires_post(client, users):
    login(client, "buyer@t.test")
    assert client.get("/auth/logout").status_code == 405


# ---- role-based access --------------------------------------------------
def test_anonymous_redirected_from_portals(client):
    for path in ("/admin/", "/seller/", "/buyer/", "/dashboard"):
        r = client.get(path)
        assert r.status_code == 302 and "/auth/login" in r.location


def test_roles_are_isolated(client, users):
    allowed = {"buyer": "/buyer/", "seller": "/seller/collectibles", "admin": "/admin/"}  # /seller/ itself redirects there
    for role, own in allowed.items():
        client.post("/auth/logout")
        login(client, f"{role}@t.test")
        for other_role, path in allowed.items():
            expected = 200 if other_role == role else 403
            assert client.get(path).status_code == expected, (role, path)


def test_dashboard_routes_by_role(client, users):
    login(client, "seller@t.test")
    assert client.get("/dashboard").location.endswith("/seller/")


# ---- change password / profile -----------------------------------------
def test_change_password(client, users):
    login(client, "buyer@t.test")
    bad = client.post("/auth/change-password", data={"current": "Nope@1234", "password": "NewPass123", "confirm": "NewPass123"})
    assert b"incorrect" in bad.data
    ok = client.post("/auth/change-password", data={"current": PASSWORD, "password": "NewPass123", "confirm": "NewPass123"})
    assert ok.status_code == 302
    assert User.query.filter_by(email="buyer@t.test").one().check_password("NewPass123")


def test_profile_update_does_not_touch_role_or_email(client, users):
    login(client, "buyer@t.test")
    client.post("/auth/profile", data={"name": "Renamed", "phone": "1234567890", "address": "New Addr",
                                       "role": "admin", "email": "x@t.test"})
    u = User.query.filter_by(email="buyer@t.test").one()
    assert u.name == "Renamed" and u.role == "buyer"


# ---- password reset -----------------------------------------------------
def test_forgot_password_is_enumeration_safe(client, users):
    a = client.post("/auth/forgot-password", data={"email": "buyer@t.test"}, follow_redirects=True)
    b = client.post("/auth/forgot-password", data={"email": "ghost@t.test"}, follow_redirects=True)
    msg = b"If that email is registered"
    assert msg in a.data and msg in b.data


def test_reset_token_flow_is_single_use(client, users):
    token = make_reset_token(users["buyer"])
    assert client.get(f"/auth/reset-password/{token}").status_code == 200
    r = client.post(f"/auth/reset-password/{token}", data={"password": "Fresh1234", "confirm": "Fresh1234"})
    assert r.status_code == 302
    assert db.session.get(User, users["buyer"].id).check_password("Fresh1234")
    # same token no longer valid once the password changed
    assert client.get(f"/auth/reset-password/{token}").status_code == 302


def test_reset_token_tampered_or_expired(client, users, monkeypatch):
    assert client.get("/auth/reset-password/garbage").status_code == 302
    token = make_reset_token(users["buyer"])
    monkeypatch.setattr("app.blueprints.auth.tokens.MAX_AGE", -1)
    assert client.get(f"/auth/reset-password/{token}").status_code == 302


# ---- CSRF ---------------------------------------------------------------
def test_csrf_enforced_when_enabled():
    class Strict(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(Strict)
    with app.app_context():
        db.create_all()
        r = app.test_client().post("/auth/register", data=REG)
        assert r.status_code == 400
        assert User.query.count() == 0
        db.drop_all()


def test_session_cookie_flags(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
