# API Reference - ChainBid

## Endpoints

### Health Check

GET /api/health/ready - Readiness check
GET /api/health/live - Liveness check
GET /api/health/metrics/summary - Metrics summary

### Auctions

GET /api/auctions - List auctions
GET /api/auctions/:id - Get auction
POST /api/auctions/:id/bid - Place bid

### Payments

POST /api/payments/:auction_id/prepare - Prepare crypto payment
POST /api/payments/:auction_id/submit - Submit tx hash
GET /api/payments/:auction_id/verify - Check status

### Users

GET /api/users/me - Current user
PUT /api/users/me/wallet - Update wallet

---

**See full details in documentation**
