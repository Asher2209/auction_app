# User Guide - ChainBid Auction System

## Getting Started

Welcome to ChainBid, a blockchain-backed auction system for collectible cards!

### System Overview

ChainBid allows you to:
- List collectible cards for auction
- Bid on cards in real-time
- Complete payments using cryptocurrency (ETH on Sepolia testnet)
- View complete ownership history of each card

### Getting Your Wallet Ready

**Step 1: Install MetaMask**
1. Download MetaMask extension for your browser
2. Create a new wallet or import an existing one
3. Save your seed phrase securely (never share it!)

**Step 2: Add Sepolia Testnet**
1. Click MetaMask → Networks → Add network
2. Enter these details:
   - Network Name: Sepolia
   - RPC URL: `https://eth-sepolia.g.alchemy.com/v2/[YOUR_KEY]`
   - Chain ID: 11155111
   - Currency: ETH

**Step 3: Get Test ETH**
1. Visit https://sepoliafaucet.com/
2. Enter your wallet address
3. Request test ETH (you'll need some for gas fees)

---

## Listing a Card

### Step 1: Verify Your Card

1. Log in to ChainBid
2. Go to **My Cards** → **Add Card**
3. Fill in card details:
   - Card Name (e.g., "Charizard Base Set")
   - Type (Pokémon, Football, Cricket, etc.)
   - Condition (Mint, Near Mint, Good, etc.)
   - Upload photo

4. Review and submit for verification
5. Admin will verify within 24 hours

### Step 2: Create Auction

Once verified, create an auction:

1. Go to **My Cards** → Select verified card
2. Click **Create Auction**
3. Set auction details:
   - Starting price (in INR)
   - Reserve price (minimum acceptable)
   - Duration (1-7 days)

4. Click **List Now**
5. Your auction is live!

### Step 3: Monitor Bids

- Check **Active Auctions** for your listings
- View real-time bids
- Receive notifications on new bids
- Can end auction early if needed

---

## Bidding on Cards

### Step 1: Find a Card

1. Go to **Browse** or **Active Auctions**
2. Filter by type, price range, or seller
3. Click on a card to view details

### Step 2: Place a Bid

1. Click **Place Bid**
2. Enter your bid amount (must be higher than current)
3. Click **Confirm Bid**
4. Your bid is recorded

**Note**: Highest bid at auction end wins the card!

### Step 3: Complete Purchase

If you win:

1. You'll receive a notification
2. Go to **My Wins**
3. Click **Complete Payment**
4. Choose payment method:
   - Crypto (ETH) - Immediate settlement
   - Bank Transfer - Manual settlement
   - Credit Card - Through payment gateway

### Step 4: Pay with Crypto (ETH)

If paying with crypto:

1. Click **Pay with Crypto**
2. Connect your MetaMask wallet
3. Review transaction details
4. Confirm in MetaMask
5. Wait for blockchain confirmation (2-5 minutes)
6. Card ownership transfers to your wallet

---

## Managing Your Profile

### Wallet Settings

1. Go to **Settings** → **Wallet**
2. Add your payout wallet address
3. This is where winnings will be sent
4. Can only be changed by you

### View Transaction History

1. Go to **My Account** → **History**
2. See all bids, purchases, and sales
3. Click on card to see complete ownership history
4. Verify transactions on blockchain

---

## Understanding Blockchain Transactions

### What Happens When You Pay?

1. **Prepare**: Your bid is locked, transaction is prepared
2. **Sign**: You approve the transaction in MetaMask
3. **Submit**: Transaction sent to Sepolia network
4. **Mine**: Network processes your transaction (1-2 minutes)
5. **Confirm**: After 2 confirmations (2-5 minutes), settled
6. **Complete**: Card ownership transfers to you

### Checking Transaction Status

1. Your transaction hash is provided immediately
2. View on Etherscan: `https://sepolia.etherscan.io/tx/{hash}`
3. Look for green checkmark (confirmed)
4. Red X means transaction failed (funds returned)

### Cost of Transactions

- Gas fees: ~0.001-0.005 ETH per transaction
- Varies by network congestion
- Fee shown before you approve
- Only charged if transaction succeeds

---

## Troubleshooting

### "Insufficient Balance"
- You need enough ETH for bid + gas fees
- Get more test ETH from faucet
- Wait for transaction to complete

### "Transaction Pending"
- Blockchain taking longer than usual
- DO NOT close browser or refresh
- Wait 5-10 minutes for confirmation
- Can check status on Etherscan

### "Transaction Failed"
- Check gas price isn't too low
- Verify wallet has enough balance
- Try again (gas will be refunded)
- Contact support if issue persists

### "Can't Connect Wallet"
- Make sure MetaMask is installed
- Check you're on Sepolia network
- Try disconnecting and reconnecting
- Clear browser cache if needed

---

## FAQs

**Q: Is this real money?**
A: No, Sepolia testnet uses test ETH only. No real money involved.

**Q: Can I use mainnet?**
A: No, currently only testnet. Will migrate to mainnet after testing.

**Q: How long do auctions last?**
A: 1-7 days, set by seller.

**Q: What if I lose a bid?**
A: Your bid remains visible on the card's history. You can bid again.

**Q: Can I cancel a bid?**
A: Only before auction ends. Requires paying a small gas fee.

**Q: Is my card safe?**
A: Yes! Your card is locked on blockchain. Only you can transfer it.

---

## Support

- Email: support@chainbid.example
- Discord: Join our community
- Docs: https://docs.chainbid.example

**Happy bidding!**
