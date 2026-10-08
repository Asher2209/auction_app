# ChainBid

A blockchain-enabled online auction system for collectible trading cards (Pokemon first), written in Python with Flask. MSc project: *Blockchain-Enabled Online Auction System Using Python with Cryptocurrency Payment*.

A seller submits a physical card. An admin reviews it against a structured checklist and, if it passes, marks it **Platform Verified**. The card then gets a platform ID (`CARD-xxxxxx`), a QR code and an ERC-721 token. The card is auctioned in real time; the winner pays in ETH through MetaMask and the token moves to them in the same transaction. The database mirrors what the chain records.

**What "Platform Verified" means:** a ChainBid admin checked the submitted details and images against a checklist. It is not a guarantee that the physical card is genuine, and the blockchain is not proof of authenticity: it records identity and ownership only.

**Test network only.** Crypto payments run on the Sepolia test network (or an in-process test chain). No real funds are involved.

## Quick start (development)

Developed and tested with Python 3.13.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then edit .env
python scripts/seed.py            # creates the tables and loads demo data
python run.py                     # http://127.0.0.1:5000
```

Use `python run.py`, not `flask run`: it serves the WebSocket connection for live bids and starts the auction scheduler.

The demo accounts (admin, sellers, buyers) are listed at the top of `scripts/seed.py`. They exist for local development only. All demo data (users, products, bids) is synthetic.

To try the whole card flow without MetaMask, set `LOCAL_CHAIN=1`: the app starts an in-process test chain with a built-in demo wallet at `/dev-wallet`.

## Wallets

A user links a wallet by signing a one-time message with it (proof of control); typing an address is not enough. Only a proven wallet can receive a card token or a payout. The app never asks for, receives or stores private keys, seed phrases or MetaMask passwords.

## Configuration

Settings come from environment variables, read from `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev-only value | Signs sessions and CSRF tokens. Production refuses to start without a random 32+ character key |
| `APP_ENV` | `development` | `production` turns on strict startup checks |
| `SECURE_COOKIES` | `0` | `1` when the site is served over HTTPS (session cookie sent over HTTPS only) |
| `DATABASE_URL` | `sqlite:///auction.db` | SQLAlchemy URL. For MySQL: `mysql+pymysql://user:pass@localhost/auction_db` |
| `ENABLE_SCHEDULER` | `1` | Background loop that starts and closes auctions |
| `ALLOW_TEST_EMAILS` | `1` | Accept reserved domains such as `.test`. Set to `0` in production |
| `APP_BASE_URL` | `http://127.0.0.1:5000` | Public address of the site, used in email links |
| `MAIL_SERVER` | empty | SMTP server. Empty: emails are printed to the server log |
| `MAIL_PORT` | `587` | SMTP port |
| `MAIL_USE_TLS` | `1` | Use STARTTLS |
| `MAIL_USERNAME` | empty | SMTP user |
| `MAIL_PASSWORD` | empty | SMTP password |
| `MAIL_DEFAULT_SENDER` | `ChainBid <noreply@chainbid.local>` | From address |
| `RPC_URL` | empty | Ethereum JSON-RPC endpoint (Sepolia). Empty disables crypto payments |
| `CONTRACT_ADDRESS` | empty | Deployed `AuctionPayment` contract |
| `COLLECTIBLE_CONTRACT_ADDRESS` | empty | Deployed `CollectibleCardToken` contract (`python scripts/deploy_contract.py token`) |
| `LISTING_REQUIRES_MINTED_TOKEN` | `0` | `1`: a card can only be listed once its token is minted and the chain confirms the owner |
| `CHAIN_ID` | `11155111` | Chain the wallet must be on (Sepolia) |
| `CHAIN_NAME` | `Sepolia` | Shown to users |
| `BLOCK_EXPLORER_TX_URL` | `https://sepolia.etherscan.io/tx/` | Prefix for transaction links |
| `CONFIRMATIONS_REQUIRED` | `2` | Blocks to wait before a payment counts |
| `INR_PER_ETH` | `320000` | Fixed exchange rate used to price auctions in ETH |
| `APP_TZ_NAME` | `IST` | Name of the display time zone. Times are stored as UTC and typed and shown in this zone |
| `APP_TZ_OFFSET_MINUTES` | `330` | Its fixed offset from UTC in minutes (IST is +5:30, no daylight saving) |
| `LOCAL_CHAIN` | `0` | `1`: development-only in-process test chain with a demo wallet |

Deploying the contracts to Sepolia needs a funded test-only wallet; see `docs/CRYPTO_SETUP.md`. The deploy script reads the deployer key from an environment variable for that one command; never put a key in `.env` or in the repository.

## Tests

```bash
.venv/Scripts/python.exe -m pytest
```

The tests use SQLite in memory and an in-process Ethereum test chain (eth-tester), so they need no network. `docs/TEST_MATRIX.md` maps each part of the test plan to the tests that cover it.

## What has and has not been verified

Verified by automated tests: registration and login, roles, listing and the admin checklist, bidding (including simultaneous bids and auction extension), payments, invoices, wallet proof of control, minting, the token transfer on payment, and the security checks (CSRF, SQL injection, file upload validation, XSS escaping). The whole card journey was also run in a browser against the local test chain with the demo wallet.

Not tested:

- **MySQL.** Everything has run on SQLite only. The code avoids SQLite-only features and the migrations target MySQL, but no MySQL run has been done, and the migrations do not yet create `blockchain_assets`, `blockchain_transfers` or `collectible_cards.platform_card_id`.
- **Real MetaMask on Sepolia.** The contracts have not been deployed to Sepolia yet; the card flow has only run on the local test chain.
- **Real email delivery.** Emails are built and captured in tests, never sent through a real SMTP server.
- **Load, multiple processes, screen readers and real mobile devices.** See the "Not covered" section of `docs/TEST_MATRIX.md`.

## Project layout

```
app/            Flask application (blueprints, models, services, templates, static files)
contracts/      Solidity sources and compiled ABIs
migrations/     Alembic migrations (MySQL)
scripts/        Seed, compile and deploy scripts
docs/           Architecture, API, admin and user guides, crypto setup, test matrix
tests/          pytest suite
```
