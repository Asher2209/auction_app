import pytest
import sqlalchemy as sa
from sqlalchemy.orm import close_all_sessions
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User, utcnow

PASSWORD = "Test@1234"


@pytest.fixture(scope="session", autouse=True)
def _test_database_exists():
    """With TEST_DATABASE_URL (Postgres in CI), make this worker's own database once; SQLite in memory needs nothing."""
    url = TestConfig.SQLALCHEMY_DATABASE_URI
    if url.startswith("sqlite"):
        return
    server, name = url.rsplit("/", 1)
    engine = sa.create_engine(f"{server}/postgres", isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        if conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).scalar() is None:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine.dispose()


@pytest.fixture
def app(tmp_path):
    app = create_app(TestConfig)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)  # never write test images into the real uploads dir
    with app.app_context():
        if TestConfig.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()
            return
        # A database server (Postgres in CI): building every table for every test would take seconds each, so the tables
        # stay and are emptied instead. create_all only adds what is missing (a test may have dropped them), and
        # emptying first also cleans up after an interrupted run.
        db.create_all()
        _empty_all_tables()
        yield app
        db.session.remove()
        # A session left open anywhere in this process (another app, a request context) keeps its transaction and its
        # locks; on Postgres the next TRUNCATE or DROP TABLE would wait for it forever. SQLite has no such locks.
        close_all_sessions()
        _empty_all_tables()  # and leave nothing behind for a test that builds its own app on the same database


if not TestConfig.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
    # A test that builds its own app ends with db.drop_all() while its own session may still be inside a transaction
    # (a request read a user within the same app context). On Postgres that DROP TABLE would wait for the session
    # forever, in the same process; so on a database server every drop first closes all sessions.
    _drop_all = db.drop_all

    def _drop_all_without_waiting(*args, **kwargs):
        close_all_sessions()
        return _drop_all(*args, **kwargs)

    db.drop_all = _drop_all_without_waiting


def _empty_all_tables():
    close_all_sessions()
    names = ", ".join(f'"{t.name}"' for t in db.metadata.sorted_tables)
    with db.engine.begin() as conn:
        conn.execute(sa.text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(email, role="member", password=PASSWORD, active=True):
    u = User(name=email.split("@")[0], email=email, role=role, phone="9000000000",
             address="Somewhere", is_active_user=active, email_verified_at=utcnow())
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def users(app):
    """Two members, named for the side each plays in most tests, and an admin."""
    return {r: make_user(f"{r}@t.test", "admin" if r == "admin" else "member") for r in ("buyer", "seller", "admin")}


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", data={"email": email, "password": password})


def prove_wallet(client, key):
    """Link the wallet of private key `key` to the signed-in user the real way: ask for the message, sign it, send it."""
    address = Account.from_key(key).address
    message = client.post("/auth/wallet/challenge", json={"address": address}).get_json()["message"]
    signature = Web3.to_hex(Account.sign_message(encode_defunct(text=message), private_key=key).signature)
    return client.post("/auth/wallet/verify", json={"address": address, "signature": signature})
