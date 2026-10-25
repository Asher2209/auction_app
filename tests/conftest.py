import pytest
import sqlalchemy as sa
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
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


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
