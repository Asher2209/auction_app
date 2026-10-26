import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.pool import NullPool

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
    # Uploaded images: "local" keeps them in UPLOAD_FOLDER; "s3" puts them in an S3-compatible bucket (services/storage.py).
    # For Cloudflare R2: S3_ENDPOINT_URL=https://<account id>.r2.cloudflarestorage.com and S3_PUBLIC_BASE_URL=the bucket's
    # public address (an r2.dev URL or your own domain).
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
    S3_BUCKET = os.environ.get("S3_BUCKET")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
    S3_REGION = os.environ.get("S3_REGION")
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
    S3_PUBLIC_BASE_URL = os.environ.get("S3_PUBLIC_BASE_URL")
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
    # Redis (optional). Set it when more than one process serves the site: live bid updates then reach browsers on every
    # web process and from the worker, and rate limits are counted once across all of them. Empty: all in this process.
    REDIS_URL = os.environ.get("REDIS_URL")
    # How many proxies (load balancer, platform router) sit in front of the app. 0 trusts no X-Forwarded-* header, so
    # nobody can fake their address; behind exactly one proxy set 1, or every visitor looks like the proxy to the limits.
    TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
    # Error reports to Sentry (free tier is enough), off unless set. Traces: share of requests timed, 0 to 1.
    SENTRY_DSN = os.environ.get("SENTRY_DSN")
    SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0"))
    ENDING_SOON_MINUTES = 10  # "auction ending" notices go out this long before the end
    # Email. With no MAIL_SERVER, emails are written to the server log instead of sent.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "MintLot <noreply@mintlot.local>")
    MAIL_ASYNC = True  # send from a background thread so requests never wait on SMTP
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")  # for links in emails
    # "Sign in with Google" (OpenID Connect). Off unless both are set; create them free in Google Cloud Console.
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
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
    LEGAL_CONTACT_EMAIL = os.environ.get("LEGAL_CONTACT_EMAIL", "privacy@mintlot.local")  # shown on the policy pages
    # Display zone: timestamps are stored as naive UTC, people type and see them in this fixed-offset zone (see timeutil.py).
    TZ_NAME = os.environ.get("APP_TZ_NAME", "IST")
    TZ_OFFSET_MINUTES = int(os.environ.get("APP_TZ_OFFSET_MINUTES", "330"))
    # Lets the seeded @demo.test accounts pass email validation. Set to 0 in production.
    ALLOW_TEST_EMAILS = os.environ.get("ALLOW_TEST_EMAILS", "1") == "1"


def _test_database_url():
    """In-memory SQLite, or TEST_DATABASE_URL (e.g. a Postgres server in CI) with one database per parallel test
    worker, named <database>_<worker>, so workers never share tables (tests/conftest.py creates them)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return "sqlite:///:memory:"
    return f"{url}_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"


class TestConfig(Config):
    TESTING = True
    ENABLE_SCHEDULER = False
    MAIL_ASYNC = False
    SQLALCHEMY_DATABASE_URI = _test_database_url()
    # On a database server, close connections when a test is done with them: tests make many short-lived apps, and
    # each keeping a pool of open connections would soon pass the server's limit (100 on a default Postgres).
    SQLALCHEMY_ENGINE_OPTIONS = {} if SQLALCHEMY_DATABASE_URI.startswith("sqlite") else {"poolclass": NullPool}
    # Whatever the developer's .env switches on, tests start from everything off; the tests that need one turn it on.
    REDIS_URL = None
    SENTRY_DSN = None
    STORAGE_BACKEND = "local"
    TRUSTED_PROXY_HOPS = 0
    GOOGLE_CLIENT_ID = None
    GOOGLE_CLIENT_SECRET = None
    MAIL_SERVER = None
    WTF_CSRF_ENABLED = False
    TZ_NAME, TZ_OFFSET_MINUTES = "UTC", 0  # tests pin UTC; tests/test_timezone.py switches to IST
    # The real .env is still loaded, but tests never reach a real blockchain or depend on the contracts deployed
    # there. Tests that need a chain start their own (see tests/test_crypto.py and tests/test_minting.py).
    RPC_URL = None
    CONTRACT_ADDRESS = None
    COLLECTIBLE_CONTRACT_ADDRESS = None
