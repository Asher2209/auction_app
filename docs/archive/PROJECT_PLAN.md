# Implementation Plan: Blockchain-Enabled Online Auction System

Stack: Flask, Flask-SQLAlchemy (SQLite in dev, MySQL-ready), Flask-Login, Flask-SocketIO, Bootstrap 5, Chart.js, Web3.py, Solidity (Sepolia), MetaMask, ReportLab, qrcode, Flask-Mail, pandas/openpyxl.

## 1. Key design decisions

| Decision | Choice | Reason |
|---|---|---|
| Database | `DATABASE_URL` env var. SQLite default, `mysql+pymysql://...` for MySQL | Runs with no setup. Switching is config only, as long as models avoid SQLite-only features |
| App structure | Flask application factory + Blueprints | Keeps modules separate and testable |
| Auction closing | APScheduler job every 15 s, plus lazy check on every bid/page load | Closing is correct even if the scheduler lags or the server restarts |
| Bid concurrency | `SELECT ... FOR UPDATE` on the auction row (MySQL). On SQLite, a single transaction with a compare-and-set `UPDATE auctions SET current_bid=:b WHERE id=:id AND current_bid<:b` | Handles the "near-simultaneous bids" test case |
| Real-time | Socket.IO rooms, one per auction (`auction_<id>`). Bids are submitted over the socket or POST, and the server re-validates | Never trust the client |
| Money | `Numeric(12,2)`; crypto amounts stored as `Numeric(38,18)` or wei integers | No float errors |
| Crypto | Pay a simple `AuctionPayment` contract on Sepolia. It takes `pay(auctionId, seller)` and forwards ETH to the seller. It emits `PaymentMade(auctionId, buyer, seller, amount)`. | Event logs let the backend verify the auction ID, recipient and amount |
| Exchange rate | Configurable `INR_PER_ETH` in config, with an optional live-rate fetch that falls back to the config value | Spec says "configured exchange rate" |
| Secrets | `.env` only. No private keys on the server. Deployer key is used only in the one-off deploy script | Matches the spec's security rules |

## 2. Folder structure

```
auction_app/
  app/
    __init__.py            # create_app, extensions
    config.py
    extensions.py          # db, login, socketio, mail, scheduler
    models/                # user, catalog, auction, payment, misc
    blueprints/
      auth/ seller/ buyer/ auctions/ payments/ admin/ reports/ api/
    services/
      auction_service.py   # place_bid, close_auction, extend logic
      payment_service.py
      blockchain_service.py  # Web3.py verification
      invoice_service.py   # ReportLab + QR
      notification_service.py
      report_service.py
    sockets/events.py
    templates/  static/ (css, js, uploads)
  contracts/AuctionPayment.sol
  scripts/deploy_contract.py, seed.py
  tests/
  migrations/              # Flask-Migrate
  requirements.txt  .env.example  run.py
```

## 3. Database schema (summary)

Matches section 23 of the spec, with these additions:
- `Users`: `is_active`, `wallet_address` (optional)
- `Products`: `approval_status` (pending/approved/rejected), plus a separate `ProductImages(product_id, path)` table in place of an `images` column
- `Auctions`: `original_end_time`, `extension_count`, `status` (scheduled/active/closed/cancelled)
- `Payments`: add `UNIQUE(auction_id)`. Statuses are pending, successful, failed.
- `CryptoPayments`: `UNIQUE(transaction_hash)` to stop hash reuse. Also `block_number`, `confirmations`, `chain_id`
- `Invoices(invoice_id, payment_id, number, pdf_path, created_at)`
- `Watchlist(user_id, product_id)`
- Indexes: `Bids(auction_id, amount)`, `Auctions(status, end_time)`

## 4. Core algorithms

**place_bid(auction, user, amount)**
1. Check the user is authenticated and has the buyer role.
2. Lock the auction row.
3. Check `status == active` and `now < end_time`.
4. Check `user.id != product.seller_id`.
5. Check `amount > current_bid` (and at least the starting price, with an optional minimum increment).
6. Insert the bid and update `current_bid` and `highest_bidder`.
7. If `end_time - now <= 60 s`, set `end_time += 120 s` and increment `extension_count`.
8. Commit, then emit `bid_update` to the room. If the end time changed, include the new `end_time`.
9. Notify the outbid buyer and the seller.

**close_auction(auction)** is idempotent and runs only on active auctions whose end time has passed. It sets the status to closed, creates the `Winner` (if there are bids), creates a pending `Payment`, notifies buyer and seller, and emits `auction_closed`.

**verify_crypto_payment(tx_hash, payment)**
1. Reject the hash if it is already recorded.
2. `w3.eth.get_transaction_receipt`. If it does not exist, return pending.
3. Check `chain_id == 11155111`, `receipt.status == 1`, and `tx.to == CONTRACT_ADDRESS`.
4. Decode the `PaymentMade` log and match `auctionId`, `seller` and `amount >= expected_wei`.
5. Require at least N confirmations (`latest - block_number >= N`).
6. On success, set payment and crypto status to confirmed and generate the invoice. On a mismatch, mark it failed with a reason.

## 5. Phases

Hour estimates total about 190.

| Phase | Scope | Hours | Done when |
|---|---|---|---|
| 0. Setup | venv, factory, config, Flask-Migrate, base templates, seed script | 8 | `flask run` shows home page, seed loads demo data |
| 1. Auth and RBAC | Register, login, logout, forgot/change password (signed token + email), profile, `role_required` decorator, CSRF (Flask-WTF) | 14 | Unauthorized access returns 403 |
| 2. Seller module | Product CRUD, multi-image upload with validation (extension, MIME, size, randomized names), edit/delete only before start | 16 | Seller can list a product and see it as pending |
| 3. Admin core | Approve/reject products, manage users and categories, approval creates the auction | 12 | Approved product becomes a scheduled auction |
| 4. Buyer module | Browse, search, filters (category, price, status), pagination, product page, watchlist, bid history | 16 | Filters and search work |
| 5. Auction engine | `place_bid`, Socket.IO rooms, countdown JS, scheduler, close and winner, anti-sniping, concurrency tests | 28 | A second browser sees bids live, auction closes by itself |
| 6. Notifications | In-app model plus bell UI with unread count, Flask-Mail with console backend in dev | 8 | All listed events produce notifications |
| 7. Simulated payment | Payment page, card/UPI/wallet forms, success/fail/pending simulation | 10 | Winner can pay and status updates |
| 8. Crypto payment | Solidity contract, Hardhat or Remix deploy, MetaMask JS (ethers.js or web3.js), rate conversion, backend verification, error cases | 30 | End-to-end Sepolia payment confirmed |
| 9. Invoice and QR | ReportLab PDF, QR with invoice, auction, payment IDs and tx hash, "Blockchain Verified" badge, public `/verify/<invoice>` page | 10 | PDF downloads and QR resolves |
| 10. Reviews and feedback | 1-5 stars after paid purchase only, one review per buyer per product, admin moderation | 6 | Review shows on product and seller pages |
| 11. Admin dashboard and analytics | KPI cards plus 9 Chart.js charts from JSON endpoints | 14 | Charts populate from seeded data |
| 12. Reports | 11 reports, each exportable to PDF (ReportLab) and Excel (openpyxl) | 12 | All exports open correctly |
| 13. Testing and hardening | pytest suite, security checks, mobile responsive pass | 16 | Test matrix below is green |
| 14. Docs and report | README, diagrams, academic report (see section 7) | 20 | Report matches implemented features |

Build order: Phases 0 to 7 give a complete demo without blockchain. Crypto (8) is isolated so it cannot block the core.

## 6. Test matrix (pytest, Flask test client, Socket.IO test client)

- **Auth**: duplicate email, weak password, wrong password, logout, reset token expiry, buyer hitting `/admin` returns 403.
- **Seller**: create, edit-before-start allowed, edit-after-start blocked, delete rules, bad file type and oversized file rejected, another seller's product returns 403.
- **Buyer**: search, filter combinations, watchlist toggle, review only after paid purchase.
- **Auction**: valid bid; equal and lower bid rejected; seller bidding rejected; bid after end rejected; extension at 59 s remaining but not at 61 s; close creates one winner; closing twice creates no duplicate; 20 threads bidding concurrently leave the highest valid bid winning.
- **Payment**: success, failure, pending, double payment blocked, invoice generated only on success.
- **Blockchain** (mocked Web3 provider for unit tests, plus manual Sepolia run): wrong chain, wrong recipient, wrong amount, reverted tx, unconfirmed tx, reused hash, wrong auction ID in the event.
- **Security**: SQL injection strings in search, XSS in descriptions and reviews (Jinja autoescape), CSRF missing token rejected, session cookie flags set.

## 7. Report outline (for later)

Chapters 1 to 8 as in the spec. Each feature in the report carries a status tag of Implemented, Proposed or Future, taken from the final test results. Diagrams are generated from the real schema and routes: architecture, use case, context/DFD, ERD, class, sequence (bid, close, crypto payment), activity, flowcharts.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Sepolia faucet or RPC unavailable | Run a local Hardhat node as a fallback with the same code path. Make `CHAIN_ID` and `RPC_URL` configurable |
| Flask-SocketIO with the scheduler and multiple workers | Single worker in dev, Redis message queue noted as future scope |
| Scope creep from 11 reports and 9 charts | Build one generic report framework (query, columns, PDF/Excel renderers) and reuse it |
| MySQL differences | Test migrations once against MySQL before submission |
| Exchange-rate drift between quote and payment | Lock the quoted wei amount on the Payment row, and accept payments at or above it |

## 9. Open items for you

1. Currency: INR display with ETH conversion (assumed from the examples).
2. Confirm that a minimum bid increment is wanted. The spec only requires "greater than the current bid".
3. Whether a Sepolia RPC key (Infura or Alchemy) and a MetaMask test wallet are available. You will need them for Phase 8.
