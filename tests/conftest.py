import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User

PASSWORD = "Test@1234"


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


def make_user(email, role="buyer", password=PASSWORD, active=True):
    u = User(name=email.split("@")[0], email=email, role=role, phone="9000000000",
             address="Somewhere", is_active_user=active)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def users(app):
    return {r: make_user(f"{r}@t.test", r) for r in ("buyer", "seller", "admin")}


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", data={"email": email, "password": password})


def prove_wallet(client, key):
    """Link the wallet of private key `key` to the signed-in user the real way: ask for the message, sign it, send it."""
    address = Account.from_key(key).address
    message = client.post("/auth/wallet/challenge", json={"address": address}).get_json()["message"]
    signature = Web3.to_hex(Account.sign_message(encode_defunct(text=message), private_key=key).signature)
    return client.post("/auth/wallet/verify", json={"address": address, "signature": signature})
