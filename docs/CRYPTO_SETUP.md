# Cryptocurrency payments: setup and demo guide

This project accepts payment in **test ETH on the Sepolia test network**. No real money is involved.
The blockchain is used only for the payment and its verification; everything else lives in the database.

There are two ways to run it:

| Mode | Needs | Use it for |
|---|---|---|
| **Local demo chain** (`LOCAL_CHAIN=1`) | nothing extra | a quick demo, development, no MetaMask or faucet |
| **Sepolia + MetaMask** | an RPC URL, test ETH, MetaMask | the real thing, for your project demonstration |

## A. Local demo chain (no MetaMask)

1. In `.env` add `LOCAL_CHAIN=1` (and leave `RPC_URL` empty). Restart with `python run.py`.
2. Open `/dev-wallet/` (signed in). It lists demo accounts. Copy the **demo seller payout wallet** address.
3. As a **seller**, paste it into *Profile -> Wallet address*.
4. Let a buyer win an auction of that seller, then open the pay page: **Cryptocurrency** tab -> *Connect wallet* -> *Pay*.
   A built-in stand-in for MetaMask signs the transaction on an in-memory chain. It is only available in this mode.

## B. Sepolia with MetaMask

### 1. Get what you need (one time, all free)
- **MetaMask**: install the browser extension and create a wallet. Write the seed phrase on paper and never share it.
  Switch MetaMask to the **Sepolia** test network (Settings -> Advanced -> show test networks).
- **Two or three test accounts** in MetaMask: a *deployer*, a *buyer* and a *seller*. The seller only needs an address.
- **Test ETH** from a Sepolia faucet (search "Sepolia faucet"; some need a small mainnet balance or a sign-in).
  Fund the *deployer* (a little) and the *buyer* (enough for your demo amounts plus gas).
- **An RPC URL**: create a free project at Infura or Alchemy, enable Sepolia, copy the HTTPS URL.

### 2. Deploy the contract (once)
Use the **deployer** account. Export its private key *only for this step* (MetaMask -> account menu -> Account details ->
Show private key). Use a throwaway test account, never one with real funds.

```powershell
$env:RPC_URL = "https://sepolia.infura.io/v3/<your project id>"
$env:DEPLOYER_PRIVATE_KEY = "<deployer private key>"
.venv\Scripts\python scripts\deploy_contract.py
Remove-Item Env:DEPLOYER_PRIVATE_KEY      # clear it straight away
```

It prints the contract address. The key is never printed or saved, and the web app never needs it.
(Alternative with no key export: paste `contracts/AuctionPayment.sol` into <https://remix.ethereum.org>, compile with
Solidity 0.8.24, choose *Injected Provider - MetaMask*, deploy, and copy the address.)

### 3. Configure the app
Add to `.env`:

```
RPC_URL=https://sepolia.infura.io/v3/<your project id>
CONTRACT_ADDRESS=0x...          # from step 2
CHAIN_ID=11155111
CHAIN_NAME=Sepolia
BLOCK_EXPLORER_TX_URL=https://sepolia.etherscan.io/tx/
CONFIRMATIONS_REQUIRED=2
INR_PER_ETH=320000              # the exchange rate used to quote prices
```

Check it before opening the browser:

```powershell
.venv\Scripts\python scripts\check_crypto_setup.py
```

### 4. Try a payment
1. **Seller**: log in, *Profile -> Wallet address*, paste the *seller* account address from MetaMask.
2. Run a short auction (minimum 5 minutes), bid as a buyer, let it end. The buyer is taken to the pay page.
3. **Buyer**: *Cryptocurrency* tab -> *Connect wallet* (MetaMask pops up) -> *Pay*. MetaMask shows the amount
   and the contract; confirm it.
4. The page shows the transaction and counts confirmations. After 2 confirmations (about 30 seconds on Sepolia)
   the payment turns *Successful*, the seller is notified, and the transaction appears on the Sepolia block explorer.

## How the payment is verified (for your report)

The browser is never trusted. After MetaMask returns a transaction hash, the server asks the blockchain itself and checks:

1. the transaction exists and has been mined;
2. it did not revert;
3. it was sent on the expected network and **to our contract**;
4. it came from the wallet the buyer connected;
5. the contract's `PaymentMade` event names **this auction**, **this seller** and **this buyer**;
6. the amount is **at least the locked quote** (price in INR / configured rate, rounded up to the wei);
7. it has the required number of confirmations.

A transaction hash can be used for one payment only. The contract also refuses a second payment for the same
auction and forwards the money to the seller immediately, so it never holds funds.

## Security notes
- The app never asks for, stores or logs a private key or seed phrase. The profile page even rejects anything that
  looks like one.
- Only the seller's *public* address is stored.
- Keep `.env` out of version control (it is already in `.gitignore`).
- This is for **test networks only**. `deploy_contract.py` refuses to run against Ethereum mainnet.
