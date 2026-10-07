import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///auction.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    APP_ENV = os.environ.get("APP_ENV", "development")  # "production" turns on strict startup checks (see security.py)
    SESSION_COOKIE_SECURE = os.environ.get("SECURE_COOKIES", "0") == "1"  # required in production (HTTPS only)
    LOGIN_MAX_AGE = timedelta(hours=8)  # a login lasts at most this long, whatever the browser does
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # whole request
    MAX_IMAGE_BYTES = 5 * 1024 * 1024  # per image
    MAX_IMAGES_PER_PRODUCT = 5
    # Bidding rules
    MIN_BID_INCREMENT = Decimal("0.01")  # a bid must beat the current bid by at least this much
    SNIPE_WINDOW_SECONDS = 60  # a bid this close to the end...
    SNIPE_EXTENSION_SECONDS = 120  # ...extends the auction by this much
    # Background loop that starts and closes auctions (off in tests)
    ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "1") == "1"
    SCHEDULER_INTERVAL_SECONDS = 5
    ENDING_SOON_MINUTES = 10  # "auction ending" notices go out this long before the end
    # Email. With no MAIL_SERVER, emails are written to the server log instead of sent.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "ChainBid <noreply@chainbid.local>")
    MAIL_ASYNC = True  # send from a background thread so requests never wait on SMTP
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")  # for links in emails
    # Cryptocurrency payments (an Ethereum TEST network only). Leave RPC_URL empty to disable them.
    RPC_URL = os.environ.get("RPC_URL")
    CONTRACT_ADDRESS = os.environ.get("CONTRACT_ADDRESS")
    CHAIN_ID = int(os.environ.get("CHAIN_ID", "11155111"))  # Sepolia
    CHAIN_NAME = os.environ.get("CHAIN_NAME", "Sepolia")
    BLOCK_EXPLORER_TX_URL = os.environ.get("BLOCK_EXPLORER_TX_URL", "https://sepolia.etherscan.io/tx/")
    CONFIRMATIONS_REQUIRED = int(os.environ.get("CONFIRMATIONS_REQUIRED", "2"))
    INR_PER_ETH = Decimal(os.environ.get("INR_PER_ETH", "320000"))  # the configured exchange rate
    CRYPTO_NOT_FOUND_TIMEOUT_MINUTES = 30  # a submitted transaction the network never shows is failed after this
    # Collectible-card identity token contract (separate from the AuctionPayment contract above).
    COLLECTIBLE_CONTRACT_ADDRESS = os.environ.get("COLLECTIBLE_CONTRACT_ADDRESS")
    # False: a registered BlockchainAsset with a matching owner wallet is enough to list a card.
    # True: the token must also be minted and the on-chain owner must match (fails closed if the chain is unreachable).
    LISTING_REQUIRES_MINTED_TOKEN = os.environ.get("LISTING_REQUIRES_MINTED_TOKEN", "0") == "1"
    # Development only: run an in-process test chain with a built-in demo wallet (no MetaMask needed).
    LOCAL_CHAIN = os.environ.get("LOCAL_CHAIN", "0") == "1"
    SIMULATED_SETTLE_SECONDS = 20  # how long a gateway-"pending" simulated payment takes to settle
    MIN_AUCTION_MINUTES = 5
    MAX_AUCTION_DAYS = 30
    CURRENCY_SYMBOL = "₹"
    # Lets the seeded @demo.test accounts pass email validation. Set to 0 in production.
    ALLOW_TEST_EMAILS = os.environ.get("ALLOW_TEST_EMAILS", "1") == "1"


class TestConfig(Config):
    TESTING = True
    ENABLE_SCHEDULER = False
    MAIL_ASYNC = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
