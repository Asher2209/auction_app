# Blockchain Contract Integration Guide

> **Superseded.** The contract described below is the first version of `CollectibleCardToken`. Its `mint()`
> has no access control (anyone could mint a token for any card), so do not use it. The current contract
> uses OpenZeppelin `ERC721` + `Ownable`: only the platform admin wallet can mint, a platform card ID can be
> minted once, and the mint is signed in MetaMask and verified on-chain by the server.
>
> 1. `cd contracts && npm install`, then `python scripts/compile_contracts.py`
> 2. Deploy: set `RPC_URL`, `DEPLOYER_PRIVATE_KEY` (throwaway test wallet) and `PLATFORM_ADMIN_WALLET` (public address),
>    then `python scripts/deploy_contract.py token`
> 3. Put the printed address in `.env` as `COLLECTIBLE_CONTRACT_ADDRESS` (not `CONTRACT_ADDRESS`, which is the payment contract)
> 4. Sign in as admin, open **Card tokens**, and mint each verified card with the admin wallet

## Deployed Contract
- **Address**: `0xC3240cFD2c9ec199Be2715F27816a1f538629307`
- **Network**: Sepolia Testnet (Chain ID: 11155111)
- **Status**: ✅ Verified and Tested
- **Etherscan**: https://sepolia.etherscan.io/address/0xC3240cFD2c9ec199Be2715F27816a1f538629307

## Integration Points

### 1. Card Verification → Blockchain Asset Creation
**File**: `app/blueprints/admin/routes_verification.py`
**Update**: `approve_card()` function (line 178-211)

Add blockchain asset creation after line 203:

```python
# Create blockchain asset with deployed contract address
collectible_card = verification.collectible_card
seller = verification.product.seller
contract_address = current_app.config.get("CONTRACT_ADDRESS")

if contract_address and seller.wallet_address:
    try:
        card_identity_service.create_blockchain_asset(
            collectible_card=collectible_card,
            owner_wallet=seller.wallet_address,
            contract_address=contract_address,
            network="sepolia"
        )
        flash(f"Card blockchain asset created! Ready for minting.", 'info')
    except Exception as e:
        current_app.logger.error(f"Blockchain asset creation failed: {e}")
        flash(f"Warning: Blockchain asset creation failed: {str(e)}", 'warning')
```

### 2. Minting Service Integration
**File**: `app/services/blockchain_minting_service.py`
**Current State**: ✅ Already configured to use `blockchain_asset.contract_address`

### 3. Transfer Service Integration  
**File**: `app/services/blockchain_transfer_service.py`
**Current State**: ✅ Already configured to use `blockchain_asset.contract_address`

### 4. Configuration (.env)
**Status**: ✅ Already configured

```
CONTRACT_ADDRESS=0xC3240cFD2c9ec199Be2715F27816a1f538629307
RPC_URL=https://eth-sepolia.g.alchemy.com/v2/...
CHAIN_ID=11155111
CHAIN_NAME=Sepolia
CONFIRMATIONS_REQUIRED=2
INR_PER_ETH=320000
```

## Complete Workflow

### Phase 1: Card Listing & Verification
1. Seller uploads collectible card
2. Admin verifies card details  
3. **→ BlockchainAsset created** (status: 'draft')

### Phase 2: Minting (Before Auction Starts)
1. Admin initiates token mint for verified card
2. System calls `contract.mint(platformId, owner, cardName)`
3. Seller signs transaction via MetaMask
4. Transaction confirmed on Sepolia
5. **→ Asset updated** (status: 'minted', token_id assigned)

### Phase 3: Auction
1. Card listed for auction
2. Buyers place bids
3. Auction closes

### Phase 4: Payment & Transfer (After Auction Closes)
1. Buyer connects wallet and approves payment
2. Crypto payment confirmed on-chain
3. **→ Payment marked successful**
4. System initiates token transfer via `contract.transferCard()`
5. Ownership transferred to buyer
6. **→ Asset updated** (status: 'transferred', new owner recorded)

## Next Steps

1. ✅ **Deploy contract** - DONE
2. ✅ **Test contract** - DONE  
3. ⏳ **Update verification route** - UPDATE routes_verification.py
4. ⏳ **Test end-to-end flow** - Follow complete workflow
5. ⏳ **Go live** - Deploy to production
