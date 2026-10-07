# Architecture - ChainBid

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Browser                             │
│              (MetaMask, MetaMask Snap)                       │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask Web Server                          │
│  ┌────────────────┐  ┌─────────────┐  ┌────────────────┐    │
│  │  Auth Layer    │  │  API Routes │  │  Admin Routes  │    │
│  └────────────────┘  └─────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Blockchain      │  │  Payment         │  │  Monitoring      │
│  Service         │  │  Service         │  │  & Logging       │
│                  │  │                  │  │                  │
│  - Minting       │  │  - Prepare       │  │  - Metrics       │
│  - Transfer      │  │  - Submit        │  │  - Health Check  │
│  - Verification  │  │  - Verify        │  │  - Alerts        │
└──────────────────┘  └──────────────────┘  └──────────────────┘
         │                    │
         ▼                    ▼
┌──────────────────────────────────────────────────────────────┐
│                      SQLite Database                          │
│  Tables: User, Product, Auction, Payment, BlockchainAsset   │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│                   Ethereum Sepolia                            │
│              Smart Contract (RPC via Alchemy)                │
│         Address: 0xC3240cFD2c9ec199Be2715F27816...          │
└──────────────────────────────────────────────────────────────┘
```

## Components

### 1. Frontend (Web Browser)

- HTML/CSS/JavaScript
- MetaMask for wallet interaction
- Real-time bid updates (WebSocket)
- QR code card scanning

### 2. Flask Backend

**Core Modules:**
- `app/blueprints/`: API routes and views
- `app/models/`: SQLAlchemy models
- `app/services/`: Business logic
  - `blockchain_service.py`: Blockchain interaction
  - `blockchain_minting_service.py`: Token minting
  - `blockchain_transfer_service.py`: Ownership transfer
  - `payment_service.py`: Payment processing
- `app/utils/`: Utilities
  - `monitoring.py`: Metrics and health checks
  - `logging_config.py`: Logging setup

### 3. Database (SQLite)

**Key Tables:**
- `user`: User accounts and wallets
- `product`: Card products
- `auction`: Active and ended auctions
- `payment`: Payment records
- `blockchain_asset`: NFT metadata

### 4. Smart Contract

**Functions:**
- `mint(platform_id, owner, card_name)`: Create token
- `transferCard(token_id, new_owner, auction_id)`: Transfer ownership
- `pay(auction_id, seller)`: Send payment to seller
- `ownerOf(token_id)`: Get current owner
- `tokensOf(owner)`: Get all tokens owned

### 5. Monitoring & Logging

**Log Files:**
- `transactions.log`: Blockchain events
- `blockchain_errors.log`: Error tracking
- `app.log`: Application events

**Metrics:**
- Transaction success rates
- RPC latency
- Confirmation times
- Error rates

---

## Data Flow: Card to Blockchain

### 1. Card Listing

```
User Upload → Verify → Create Blockchain Asset → Ready for Auction
```

### 2. Auction Creation

```
Seller creates auction → Set starting price → Auction goes live
```

### 3. Bidding

```
Buyer places bid → Update highest → Notify seller/previous bidder
```

### 4. Payment (Winner)

```
Prepare tx → Sign in MetaMask → Submit tx hash → Verify on chain → Transfer token
```

### 5. Blockchain Settlement

```
RPC submits tx → Network mines → Confirmations → Ownership transfers → Audit trail
```

---

## Security Layers

### 1. Application Level

- Input validation
- SQL injection prevention (SQLAlchemy ORM)
- XSS protection (templating)
- CSRF tokens
- Rate limiting
- Authentication/Authorization

### 2. Blockchain Level

- Smart contract audit
- CEI pattern for reentrancy protection
- Access control (msg.sender checks)
- Event logging for transparency
- Immutable transaction history

### 3. Network Level

- HTTPS/TLS encryption
- Wallet verification (signature)
- Test network isolation (Sepolia testnet)

---

## Error Handling

### Retry Logic

```
RPC Call
  │
  ├─ Success → Return data
  │
  └─ Failure (transient)
       ├─ Retry 1 (wait 1s)
       ├─ Retry 2 (wait 2s)
       └─ Retry 3 (wait 4s)
            └─ Failure → User-friendly error
```

### User Feedback

```
Transaction States:
- Pending: Waiting for user to sign
- Processing: Submitted to blockchain
- Confirming: Awaiting confirmations
- Confirmed: Settled on blockchain
- Failed: Transaction reverted
```

---

## Performance Considerations

### Database

- Indexed on auction_id, user_id, status
- Connection pooling for concurrency
- Logging queries > 1 second

### RPC

- Alchemy node for high availability
- 1000 req/min rate limit
- Retry with backoff for transient failures

### Caching

- Session cache (user data)
- Auction cache (updates via WebSocket)
- Metrics cache (1-minute windows)

---

## Scalability

### Current Capacity

- ~1000 concurrent users
- ~10 auctions per second
- ~100 transactions per second

### To Scale Further

- Database sharding by user_id
- Caching layer (Redis)
- Load balancer (nginx)
- Multiple app servers
- Database read replicas

---

**Last Updated**: 2026-10-07
