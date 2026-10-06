# Phase B: Token Minting & Ownership Transfer

## Overview
Phase B adds blockchain minting and ownership transfer capabilities.

## Architecture

```
PHASE B WORKFLOW:

Card Verified (Phase A Complete)
    ↓
[Step 1] Smart Contract Mint
    ↓
Mint Transaction Submitted
    ↓
[Step 2] Verify Mint Transaction
    ↓
Token Created on Blockchain
    ↓
BlockchainAsset Updated (status: minted)
    ↓
Auction Runs
    ↓
Winner Pays (Cryptocurrency)
    ↓
Payment Confirmed
    ↓
[Step 3] Smart Contract Transfer Ownership
    ↓
Transfer Transaction Submitted
    ↓
[Step 4] Verify Transfer Transaction
    ↓
Ownership Transferred on Blockchain
    ↓
BlockchainAsset Owner Updated
    ↓
BlockchainTransfer Record Created
    ↓
Complete
```

## Components to Implement

### 1. Smart Contract Updates
- Add `mint()` function - Create token for card
- Add `transferOwnership()` function - Transfer token after sale
- Add `balanceOf()` view - Check ownership
- Add events for minting and transfers

### 2. Blockchain Minting Service
- `initiate_mint()` - Prepare minting transaction
- `verify_mint()` - Check blockchain confirmation
- `complete_mint()` - Update BlockchainAsset status
- Error handling and retry logic

### 3. Ownership Transfer Service
- `initiate_transfer()` - Prepare transfer transaction
- `verify_transfer()` - Check blockchain confirmation
- `complete_transfer()` - Update ownership records
- Synchronize MySQL with blockchain

### 4. Admin Integration
- Add "Mint Token" button in verification dashboard
- Show minting status and transaction
- Manual retry capability

### 5. Payment Integration
- Trigger ownership transfer after payment confirmed
- Track transfer status
- Handle failed transfers

### 6. Audit Trail
- BlockchainTransfer records for all transfers
- Transaction hashes and block numbers
- Ownership history per card

## Files to Create/Modify

### New Files
- `contracts/CollectibleCardToken.sol` - Enhanced smart contract
- `contracts/build/CollectibleCardToken.json` - Compiled ABI
- `app/services/blockchain_minting_service.py` - Minting logic
- `app/services/blockchain_transfer_service.py` - Transfer logic
- `app/blueprints/admin/routes_minting.py` - Admin minting UI

### Modified Files
- `contracts/AuctionPayment.sol` - Add transfer logic
- `app/blueprints/admin/routes_verification.py` - Add mint button
- `app/blueprints/payments/routes.py` - Trigger transfer on payment
- `app/services/payment_service.py` - Call transfer service

## Database Changes
- None required - BlockchainAsset and BlockchainTransfer ready
- New blockchain_asset.status values: minting, transferring
- New blockchain_transfer records on every ownership change

## Implementation Order

1. **Step 1**: Update smart contract with mint and transfer functions
2. **Step 2**: Create blockchain minting service
3. **Step 3**: Integrate minting into admin verification
4. **Step 4**: Create blockchain transfer service
5. **Step 5**: Integrate transfer into payment workflow
6. **Step 6**: Add blockchain synchronization
7. **Step 7**: Test end-to-end workflow

## Key Decisions

### Why Separate Mint & Transfer Functions?
- Mint: 1:1 mapping of physical card to blockchain token
- Transfer: Happens after auction payment
- Two separate events ensure clear tracking

### Why Not One Transaction?
- Minting: Seller initiates, blockchain verifies card exists
- Transfer: Buyer initiates, payment must be confirmed first
- Separating allows error recovery between steps

### Synchronization Strategy
- MySQL is source of truth for application state
- Blockchain confirms ownership for settlement
- On mismatch, admin intervention required
- Log all synchronization events

## Testing Strategy

1. **Unit Tests**: Test each service independently
2. **Integration Tests**: Test mint → transfer flow
3. **Failure Tests**: Test error handling and retries
4. **Security Tests**: Verify authorization checks

## Success Criteria

- Token minting works end-to-end
- Ownership transfers correctly
- BlockchainAsset status matches blockchain
- Audit trail complete and accurate
- Error recovery working
- All tests passing

