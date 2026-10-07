"""Deploy contracts/AuctionPayment.sol to the network at RPC_URL (use a TEST network such as Sepolia).

    $env:RPC_URL = "https://sepolia.infura.io/v3/<project id>"
    $env:DEPLOYER_PRIVATE_KEY = "<private key of a TEST-ONLY wallet>"
    python scripts/deploy_contract.py            # the AuctionPayment contract
    $env:PLATFORM_ADMIN_WALLET = "<PUBLIC address of the admin wallet that will mint in MetaMask>"
    python scripts/deploy_contract.py token      # the CollectibleCardToken contract (owner = that wallet)

Security notes
* Use a throwaway wallet that holds only free test ETH, never a wallet with real funds.
* The key is read from the environment for this one command, signs locally and is never printed,
  logged or written to disk. The web application itself never needs or sees any private key.
* Clear it afterwards:  Remove-Item Env:DEPLOYER_PRIVATE_KEY
"""
import json
import os
import sys
from pathlib import Path

from eth_account import Account
from web3 import Web3

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "contracts" / "build" / "AuctionPayment.json"
TOKEN_ARTIFACT = ROOT / "contracts" / "build" / "CollectibleCardToken.json"


def deploy(w3, key, artifact=ARTIFACT, constructor_args=()):
    """Sign and send the deployment with `key`; return (contract_address, chain_id). Exits on unsafe conditions."""
    chain_id = w3.eth.chain_id
    account = Account.from_key(key)
    balance = w3.eth.get_balance(account.address)
    print(f"Network chain id : {chain_id}")
    print(f"Deployer         : {account.address}  ({Web3.from_wei(balance, 'ether')} ETH)")
    if chain_id == 1:
        sys.exit("Refusing to deploy to Ethereum mainnet. This project is for TEST networks only.")
    if balance == 0:
        sys.exit("The deployer has no test ETH. Get some from a faucet first.")

    art = json.loads(artifact.read_text())
    contract = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    tx = contract.constructor(*constructor_args).build_transaction({
        "from": account.address, "nonce": w3.eth.get_transaction_count(account.address), "chainId": chain_id,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Deploy tx        : {Web3.to_hex(tx_hash)}  (waiting for it to be mined...)")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if receipt.status != 1:
        sys.exit("Deployment failed on chain.")
    return receipt.contractAddress, chain_id


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "payment"
    if which not in ("payment", "token"):
        sys.exit("Usage: python scripts/deploy_contract.py [payment|token]")
    rpc, key = os.environ.get("RPC_URL"), os.environ.get("DEPLOYER_PRIVATE_KEY")
    if not rpc or not key:
        sys.exit("Set RPC_URL and DEPLOYER_PRIVATE_KEY in the environment first (see the docstring).")
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        sys.exit("Could not connect to RPC_URL.")
    if which == "token":
        admin = os.environ.get("PLATFORM_ADMIN_WALLET", "")
        if not Web3.is_address(admin):
            sys.exit("Set PLATFORM_ADMIN_WALLET to the PUBLIC address (0x + 40 hex) of the wallet that will sign mints in MetaMask.")
        address, chain_id = deploy(w3, key, TOKEN_ARTIFACT, (Web3.to_checksum_address(admin),))
        variable = "COLLECTIBLE_CONTRACT_ADDRESS"
    else:
        address, chain_id = deploy(w3, key)
        variable = "CONTRACT_ADDRESS"
    print()
    print("Deployed. Put these in your .env file:")
    print(f"  RPC_URL={rpc}")
    print(f"  {variable}={address}")
    print(f"  CHAIN_ID={chain_id}")


if __name__ == "__main__":
    main()
