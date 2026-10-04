"""Compile contracts/AuctionPayment.sol into contracts/build/AuctionPayment.json (abi + bytecode).

The application only needs the ABI at runtime, so the compiled file is committed and the
compiler is needed only when the contract source changes.

    python scripts/compile_contract.py
"""
import json
from pathlib import Path

import solcx

ROOT = Path(__file__).resolve().parent.parent
SOLC_VERSION = "0.8.24"


def main():
    if SOLC_VERSION not in [str(v) for v in solcx.get_installed_solc_versions()]:
        solcx.install_solc(SOLC_VERSION)
    source = ROOT / "contracts" / "AuctionPayment.sol"
    out = solcx.compile_files(
        [str(source)], output_values=["abi", "bin"], solc_version=SOLC_VERSION,
        optimize=True, optimize_runs=200,
    )
    (key,) = [k for k in out if k.endswith(":AuctionPayment")]
    artifact = {"contractName": "AuctionPayment", "solc": SOLC_VERSION,
                "abi": out[key]["abi"], "bytecode": "0x" + out[key]["bin"]}
    target = ROOT / "contracts" / "build" / "AuctionPayment.json"
    target.write_text(json.dumps(artifact, indent=2))
    print(f"Wrote {target.relative_to(ROOT)} ({len(artifact['bytecode']) // 2 - 1} bytes of bytecode)")


if __name__ == "__main__":
    main()
