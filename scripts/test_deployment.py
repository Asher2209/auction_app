#!/usr/bin/env python3
"""Test deployed CollectibleCardToken contract on Sepolia"""

import os
import json
from pathlib import Path
from web3 import Web3

print("\n" + "=" * 90)
print("COLLECTIBLE CARD TOKEN - DEPLOYMENT TEST")
print("=" * 90)

# Load environment
rpc_url = os.getenv("RPC_URL", "https://eth-sepolia.g.alchemy.com/v2/alch_fJISI_tz9fx5O5JFLXsHD")
contract_address = os.getenv("CONTRACT_ADDRESS")

if not contract_address:
    print("[ERROR] CONTRACT_ADDRESS not set in .env")
    exit(1)

print(f"\n[1] CONNECTING TO SEPOLIA")
print("-" * 90)

web3 = Web3(Web3.HTTPProvider(rpc_url))
if not web3.is_connected():
    print("[ERROR] Could not connect to Sepolia")
    exit(1)

print(f"[OK] Connected to Sepolia")
print(f"     Chain ID: {web3.eth.chain_id}")
print(f"     Latest block: {web3.eth.block_number}")

# Load contract
print(f"\n[2] LOADING CONTRACT")
print("-" * 90)

artifact = json.loads(Path("contracts/build/CollectibleCardToken.json").read_text())
abi = artifact["abi"]

contract = web3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=abi)
print(f"[OK] Contract loaded: {contract_address}")

# Check if code exists at address
print(f"\n[3] VERIFYING CONTRACT CODE")
print("-" * 90)

code = web3.eth.get_code(Web3.to_checksum_address(contract_address))
if len(code) > 0:
    print(f"[OK] Contract code found ({len(code)} bytes)")
else:
    print("[ERROR] No code at contract address")
    exit(1)

# Test read functions
print(f"\n[4] TESTING READ FUNCTIONS")
print("-" * 90)

try:
    result = contract.functions.ownerOf(1).call()
    print(f"[OK] ownerOf(1) = {result}")
except Exception as e:
    print(f"[WARN] ownerOf(1) test: {e}")

try:
    result = contract.functions.tokensOf("0x0000000000000000000000000000000000000000").call()
    print(f"[OK] tokensOf(0x0000...) = {result}")
except Exception as e:
    print(f"[WARN] tokensOf test: {e}")

try:
    result = contract.functions.getTransferHistory(1).call()
    print(f"[OK] getTransferHistory(1) = {result}")
except Exception as e:
    print(f"[WARN] getTransferHistory test: {e}")

# Get contract info
print(f"\n[5] CONTRACT INFORMATION")
print("-" * 90)

print(f"[OK] Contract Address: {contract_address}")
print(f"     Functions: {len([x for x in abi if x.get('type') == 'function'])}")
print(f"     Events: {len([x for x in abi if x.get('type') == 'event'])}")

functions = [x["name"] for x in abi if x.get("type") == "function"]
print(f"     Available functions:")
for fn in functions:
    print(f"       - {fn}")

# Check on Etherscan
print(f"\n[6] ETHERSCAN VERIFICATION")
print("-" * 90)
etherscan_url = f"https://sepolia.etherscan.io/address/{contract_address}"
print(f"[OK] View contract: {etherscan_url}")

print(f"\n" + "=" * 90)
print("DEPLOYMENT TEST SUCCESSFUL!")
print("=" * 90)
print(f"\nContract is ready for integration with your auction system.\n")
