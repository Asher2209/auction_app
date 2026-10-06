#!/usr/bin/env python3
"""Deploy CollectibleCardToken to Sepolia testnet"""

import os
import sys
import json
import time
from pathlib import Path

print("\n" + "=" * 90)
print("COLLECTIBLE CARD TOKEN - SEPOLIA DEPLOYMENT")
print("=" * 90)

# Check credentials
deployer_address = os.getenv("DEPLOYER_ADDRESS", "").strip()
deployer_key = os.getenv("DEPLOYER_PRIVATE_KEY", "").strip()

print("\n[CHECK] DEPLOYMENT CREDENTIALS")
print("-" * 90)

if not deployer_address or not deployer_key:
    print("""
[ERROR] DEPLOYMENT CREDENTIALS NOT SET

Set environment variables:
  Windows: set DEPLOYER_ADDRESS=0x... & set DEPLOYER_PRIVATE_KEY=0x...
  Mac/Linux: export DEPLOYER_ADDRESS=0x... && export DEPLOYER_PRIVATE_KEY=0x...
""")
    sys.exit(1)

print(f"[OK] Deployer address: {deployer_address}")
print(f"[OK] Private key configured")

try:
    from web3 import Web3
except ImportError:
    print("[ERROR] Web3.py not installed: pip install web3")
    sys.exit(1)

# Connect to Sepolia
rpc_url = os.getenv("RPC_URL", "https://eth-sepolia.g.alchemy.com/v2/alch_fJISI_tz9fx5O5JFLXsHD")
web3 = Web3(Web3.HTTPProvider(rpc_url))

print("\n[CONNECT] SEPOLIA TESTNET")
print("-" * 90)

if not web3.is_connected():
    print("[ERROR] Could not connect to Sepolia")
    sys.exit(1)

print(f"[OK] Connected to Sepolia")
print(f"     Chain ID: {web3.eth.chain_id}")
print(f"     Latest block: {web3.eth.block_number}")
print(f"     Gas price: {web3.eth.gas_price / 1e9:.2f} Gwei")

# Check balance
balance = web3.eth.get_balance(deployer_address)
balance_eth = web3.from_wei(balance, "ether")

print(f"\n[CHECK] ACCOUNT BALANCE")
print("-" * 90)
print(f"[OK] Balance: {balance_eth:.4f} ETH")

if balance_eth < 0.05:
    print("\n[ERROR] Insufficient balance!")
    print(f"Need: 0.05 ETH")
    print(f"Have: {balance_eth:.4f} ETH")
    print(f"\nGet test ETH: https://sepoliafaucet.com/")
    sys.exit(1)

# Load contract
print("\n[LOAD] COMPILED CONTRACT")
print("-" * 90)

artifact = json.loads(Path("contracts/build/CollectibleCardToken.json").read_text())
bytecode = artifact.get("bytecode") or artifact.get("bin")
abi = artifact.get("abi", [])

if not bytecode.startswith("0x"):
    bytecode = "0x" + bytecode

print(f"[OK] Contract loaded")
print(f"     ABI: {len([x for x in abi if x.get('type') == 'function'])} functions")
print(f"     Bytecode: {len(bytecode) // 2} bytes")

# Deploy
print("\n[DEPLOY] CONTRACT")
print("-" * 90)

try:
    Contract = web3.eth.contract(abi=abi, bytecode=bytecode)
    
    # Estimate gas
    constructor = Contract.constructor()
    gas_estimate = web3.eth.estimate_gas({
        "from": deployer_address,
        "data": constructor.data_in_transaction
    })
    
    gas_with_buffer = gas_estimate + 100000
    gas_price = web3.eth.gas_price
    estimated_cost = web3.from_wei(gas_with_buffer * gas_price, "ether")
    
    print(f"[OK] Gas estimate: {gas_estimate:,}")
    print(f"     Estimated cost: {estimated_cost:.6f} ETH")
    
    # Get nonce
    nonce = web3.eth.get_transaction_count(deployer_address)
    
    # Build transaction
    tx_data = constructor.build_transaction({
        "from": deployer_address,
        "gas": gas_with_buffer,
        "gasPrice": gas_price,
        "nonce": nonce,
    })
    
    print(f"[OK] Transaction built")
    
    # Sign and send
    print("\n[SIGN] TRANSACTION")
    print("-" * 90)
    
    signed_txn = web3.eth.account.sign_transaction(tx_data, deployer_key)
    print(f"[OK] Transaction signed")
    
    print("\n[SEND] TO SEPOLIA")
    print("-" * 90)
    
    tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
    print(f"[OK] Sent! Hash: {tx_hash.hex()}")
    
    # Wait for receipt
    print("\n[WAIT] MINING (30-60 seconds)...")
    print("-" * 90)
    
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    contract_address = receipt["contractAddress"]
    
    print(f"[OK] Mined in block {receipt['blockNumber']}")
    print(f"[OK] Gas used: {receipt['gasUsed']:,}")
    
    # Save to .env
    print("\n[SAVE] CONFIGURATION")
    print("-" * 90)
    
    env_file = Path(".env")
    env_content = env_file.read_text() if env_file.exists() else ""
    
    import re
    if "CONTRACT_ADDRESS=" in env_content:
        env_content = re.sub(
            r"CONTRACT_ADDRESS=0x[a-fA-F0-9]*",
            f"CONTRACT_ADDRESS={contract_address}",
            env_content
        )
    else:
        env_content += f"\nCONTRACT_ADDRESS={contract_address}\n"
    
    env_file.write_text(env_content)
    
    # Save deployment record
    deployment_record = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "network": "sepolia",
        "chainId": 11155111,
        "contractAddress": contract_address,
        "deployerAddress": deployer_address,
        "transactionHash": tx_hash.hex(),
        "blockNumber": receipt["blockNumber"],
        "gasUsed": receipt["gasUsed"],
        "explorerUrl": f"https://sepolia.etherscan.io/address/{contract_address}"
    }
    
    Path("contracts/deployment_record.json").write_text(json.dumps(deployment_record, indent=2))
    
    print("\n" + "=" * 90)
    print("DEPLOYMENT SUCCESSFUL!")
    print("=" * 90)
    print(f"\nContract Address: {contract_address}")
    print(f"Etherscan: https://sepolia.etherscan.io/address/{contract_address}")
    print(f"Updated .env with CONTRACT_ADDRESS\n")
    
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)



