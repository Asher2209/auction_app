# ChainBid: a blockchain-enabled online auction system

A web-based auction platform built with **Python and Flask**. Sellers list products, buyers bid in real time,
the system closes auctions and picks winners automatically, and winners pay either through a **simulated**
payment gateway or with **test ETH on an Ethereum test network** (Sepolia), verified on the blockchain.

It uses a hybrid design: an ordinary relational database holds the application data, and the blockchain is used
only where it adds value, for payments and their verification. **No real money is involved anywhere.**

> Academic project. The cryptocurrency feature runs on a test network (or a local demo chain) with valueless
> test ETH. Payments in the "conventional" path are simulated.

## Contents
1. [What it does](#what-it-does) · 2. [Architecture](#architecture) · 3. [Quick start](#quick-start) · 4. [Configuration](#configuration)
5. [Demo data](#demo-data) · 6. [Cryptocurrency payments](#cryptocurrency-payments) · 7. [Tests](#tests)
8. [Security](#security) · 9. [Status: what is and is not verified](#status) · 10. [Project layout](#project-layout)

## What it does

| Role | Can do |
|---|---|
| **Buyer** | Register, browse, search and filter auctions, watch items, bid live, see bid history, pay for won auctions (card / UPI / wallet simulation or ETH), download PDF invoices, rate and review purchases, get notifications |
| **Seller** | List products with several images, edit or delete them before the auction starts, follow bids and winners, see payment status and reviews, set a payout wallet |
| **Administrator** | Approve or reject listings, remove fake ones, manage users and categories, moderate reviews, read feedback, see a dashboard, charts (Chart.js) and **11 reports** exportable to PDF and Excel |

Core behaviour:
* **Real-time bidding** with Flask-SocketIO: everyone viewing an auction sees new bids, the countdown and closing without refreshing.
* **Server-side bid rules**: logged in, buyer account, not the seller, auction active, higher than the current bid (first bid at least the starting price).
* **Anti-sniping**: a valid bid in the last 60 seconds extends the auction by 2 minutes.
* **Automatic closing**: a background loop starts and closes auctions; the highest bidder becomes the winner and a payment is created.
* **Payments**: a deterministic simulated gateway (card, UPI, wallet; success, failure, pending) and optional crypto payment through a small Solidity contract.
* **Blockchain verification**: the server checks the transaction on chain (network, contract, sender, event, auction, seller, amount, confirmations) instead of trusting the browser.
* **Invoices**: PDF with a QR code that opens a public verification page; crypto invoices show "Blockchain Verified" and the transaction hash.
* **Notifications**: in-app (live bell), email (Flask-Mail), including "auction ending soon".

## Architecture

```
Browser (Bootstrap 5, JavaScript, Chart.js, Socket.IO client, MetaMask)
   |  HTTPS / WebSocket
Flask application factory
   |-- blueprints: auth, seller, buyer, auctions, payments, invoices, reviews, notifications, admin
   |-- services:   auction engine, payments, blockchain (Web3.py), invoices (ReportLab + QR), reports (openpyxl), analytics, mail
   |-- Flask-SocketIO (one room per auction, one per user) + background scheduler thread
   |
SQLAlchemy ORM --> SQLite (default) or MySQL          Web3.py --> Ethereum test network --> AuctionPayment.sol <-- MetaMask
```

* **Concurrency**: every state change (bid, close, payment, verification) is a compare-and-set `UPDATE`, so simultaneous
  bids, double clicks and parallel verifiers cannot corrupt state. This is covered by multi-threaded tests.
* **Money** is `Numeric(12,2)` in the database and `Decimal` in code; ETH amounts are exact integers (wei).

## Quick start

Requires Python 3.11+ (developed on 3.13) on Windows, macOS or Linux.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env                       # then edit SECRET_KEY
$env:FLASK_APP = "run.py"
.venv\Scripts\flask db upgrade               # create the database
.venv\Scripts\python scripts\seed.py         # demo users, categories, live auctions
.venv\Scripts\python run.py                  # http://127.0.0.1:5000
```

Always start the app with `python run.py` (not `flask run`): it serves WebSockets and starts the auction scheduler.

Demo accounts (all use the password printed by `seed.py`): `admin@demo.test`, `seller1@demo.test`, `seller2@demo.test`,
`buyer1@demo.test`, `buyer2@demo.test`. These exist only in a development database.

## Configuration

Settings come from environment variables (a `.env` file is read automatically). See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev value | Signs sessions and tokens. **Must be random, 32+ characters, in production** |
| `DATABASE_URL` | `sqlite:///auction.db` | e.g. `mysql+pymysql://user:pass@localhost/auction_db` |
| `APP_ENV` | `development` | `production` turns on strict startup checks: the app refuses to start with an unsafe setup |
| `SECURE_COOKIES` | `0` | Set to `1` behind HTTPS (required in production) |
| `ALLOW_TEST_EMAILS` | `1` | Accept reserved `.test` addresses (demo accounts). Must be `0` in production |
| `ENABLE_SCHEDULER` | `1` | Background loop that starts and closes auctions |
| `APP_BASE_URL` | `http://127.0.0.1:5000` | Public address, used in emails and invoice QR codes (https in production) |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | unset | SMTP. With no server, emails are printed to the log in development |
| `RPC_URL`, `CONTRACT_ADDRESS`, `CHAIN_ID`, `CHAIN_NAME`, `BLOCK_EXPLORER_TX_URL`, `CONFIRMATIONS_REQUIRED`, `INR_PER_ETH` | Sepolia, rate 320000 | Crypto payments (see below). Empty `RPC_URL` disables them |
| `LOCAL_CHAIN` | `0` | Development-only in-memory chain with a demo wallet. Refuses to run next to a real `RPC_URL` |

Production checklist: `APP_ENV=production`, a strong `SECRET_KEY`, `SECURE_COOKIES=1`, `ALLOW_TEST_EMAILS=0`,
an `https://` `APP_BASE_URL`, SMTP settings, MySQL, and run behind an HTTPS reverse proxy.

## Demo data

```powershell
.venv\Scripts\python scripts\seed_demo_activity.py    # several months of auctions, bids, payments and reviews
```

This fills the analytics charts and reports. **Its crypto payments are synthetic** (made-up hashes, labelled
"Demo (synthetic)"): there is no blockchain behind them. Use it on a development database only.

## Cryptocurrency payments

Full guide: [docs/CRYPTO_SETUP.md](docs/CRYPTO_SETUP.md). Two modes:
* **Local demo chain** (`LOCAL_CHAIN=1`): no wallet, faucet or RPC needed; a built-in stand-in for MetaMask signs on an in-memory chain.
* **Sepolia + MetaMask**: deploy `contracts/AuctionPayment.sol` with `scripts/deploy_contract.py`, set the variables above, and
  check them with `scripts/check_crypto_setup.py`.

The app never asks for, stores or logs a private key or seed phrase.

## Tests

```powershell
.venv\Scripts\python -m pytest -q          # about 720 tests, roughly 12 minutes (the concurrency tests are the slow ones)
```

The suite covers authentication, seller and buyer flows, the auction engine (including multi-threaded races), payments,
the smart contract on a real EVM (eth-tester), invoices (the printed QR code is scanned back), reviews, analytics, all
11 reports and both export formats, notifications, accessibility, and a dedicated security suite.
[docs/TEST_MATRIX.md](docs/TEST_MATRIX.md) maps the project brief's test plan to the exact tests.

## Security

Implemented and tested:
* Passwords hashed with a salted slow hash; strength rules; account-enumeration-safe messages.
* CSRF protection on every state-changing request; HttpOnly, SameSite session cookie (Secure when configured);
  logins end after 8 hours **on the server**; Flask-Login "strong" session protection.
* Throttling: failed logins (per client+account, per client, per account), registration, password reset, bidding, payments.
* Role-based access with **default-deny** verified over every route; ownership checks return 404 so ids cannot be probed.
* A Content-Security-Policy with no inline scripts, Subresource Integrity on every third-party file, `X-Frame-Options`,
  `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS when served securely; signed-in pages are never cached.
* Output escaping everywhere (templates, PDF text, Excel formula-injection guard); SQL through the ORM only.
* Uploads validated by content (Pillow), re-named randomly, size and pixel limits.
* SQLite foreign keys enforced; production start-up checks; errors never show internals.

Scans run for this phase: `pip-audit` found no known vulnerabilities in the installed packages; `bandit` found 5 low-severity
items, all reviewed and benign (the string the app uses to *reject* the default secret in production, `escape()` used for output
escaping, demo-password and random-seed constants in the development seed scripts).

## Status

| Area | State |
|---|---|
| Everything above on SQLite, automated tests | Implemented and passing |
| Browser checks (desktop and 375 px phone width) of the main flows, charts, reports, payments, crypto on the local chain | Done by hand |
| MySQL | **Not tested**: the code uses portable SQL, but only SQLite has been run |
| Real Sepolia network with MetaMask | **Not tested**: only the local chain and the in-process EVM were run. Follow docs/CRYPTO_SETUP.md |
| Real SMTP delivery | **Not tested**: emails are verified in tests and the dev log |
| Screen reader and keyboard-only use, colour contrast | Structural checks automated; assistive-technology testing not done |
| Load and performance testing | Not done |

Known limitations: rate limiting is per process (use a shared store such as Redis with several workers); PDF text is Latin-1
(amounts print as `INR`, other scripts as `?`); no per-user email opt-out; no payment deadline for unpaid winners; no
administrator audit log; no two-factor login.

## Project layout

```
app/            Flask application (blueprints, services, models, templates, static)
contracts/      AuctionPayment.sol and its compiled ABI
docs/           CRYPTO_SETUP.md, TEST_MATRIX.md
migrations/     Alembic migrations
scripts/        seed, demo data, contract compile/deploy, crypto setup check
tests/          pytest suite
run.py          start the app (HTTP + WebSocket + scheduler)
```
