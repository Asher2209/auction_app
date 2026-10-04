"""Check that the crypto settings in .env actually work, before you try a payment in the browser.

    python scripts/check_crypto_setup.py

It reads RPC_URL, CONTRACT_ADDRESS and CHAIN_ID the same way the app does. Read-only: it sends no
transactions and needs no keys.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web3 import Web3  # noqa: E402

from app import create_app  # noqa: E402
from app.services import blockchain_service as bc  # noqa: E402


def check(app):
    """Run every check, printing OK/FAIL lines. Returns the list of problems (empty = all good)."""
    cfg = app.config
    problems = []

    def ok(msg):
        print(f"  OK   {msg}")

    def bad(msg):
        print(f"  FAIL {msg}")
        problems.append(msg)

    with app.app_context():
        print("Crypto configuration")
        if not cfg.get("RPC_URL") and "web3" not in app.extensions:
            bad("RPC_URL is empty (crypto payments stay disabled)")
        if not cfg.get("CONTRACT_ADDRESS"):
            bad("CONTRACT_ADDRESS is empty (run scripts/deploy_contract.py)")
        if problems:
            return problems

        w3 = bc.get_web3()
        if not w3.is_connected():
            bad("cannot connect to RPC_URL")
            return problems
        ok(f"connected to the node (latest block {w3.eth.block_number})")

        chain_id = w3.eth.chain_id
        (ok if chain_id == cfg["CHAIN_ID"] else bad)(f"node chain id {chain_id}, CHAIN_ID setting {cfg['CHAIN_ID']}")
        if chain_id == 1:
            bad("this is Ethereum MAINNET. Only use a test network.")

        addr = cfg["CONTRACT_ADDRESS"]
        if not Web3.is_address(addr):
            bad("CONTRACT_ADDRESS is not a valid address")
            return problems
        code = w3.eth.get_code(Web3.to_checksum_address(addr))
        if code:
            ok(f"contract code at {addr}: {len(code)} bytes")
            try:
                bc._contract(w3).functions.paid(0).call()
                ok("the contract answers paid(auctionId) as expected")
            except Exception as e:  # noqa: BLE001
                bad(f"contract call failed: {e}")
        else:
            bad(f"no contract found at {addr} on this network")

        ok(f"exchange rate: {cfg['INR_PER_ETH']} INR per ETH; {cfg['CONFIRMATIONS_REQUIRED']} confirmations required")
    return problems


def main():
    problems = check(create_app())
    print()
    print("All good: crypto payments are enabled." if not problems else f"{len(problems)} problem(s) found.")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
