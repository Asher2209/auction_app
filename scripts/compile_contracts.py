"""Compile contracts/CollectibleCardToken.sol into contracts/build/CollectibleCardToken.json.

    cd contracts && npm install      # once: fetches the pinned OpenZeppelin sources
    python scripts/compile_contracts.py
"""
import json
import sys
from pathlib import Path

import solcx

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
SOLC_VERSION = "0.8.24"
NAME = "CollectibleCardToken"


def compile_token():
    if not (CONTRACTS / "node_modules" / "@openzeppelin").exists():
        sys.exit("OpenZeppelin is missing: run 'npm install' inside the contracts folder first.")
    if SOLC_VERSION not in [str(v) for v in solcx.get_installed_solc_versions()]:
        solcx.install_solc(SOLC_VERSION)
    out = solcx.compile_files(
        [str(CONTRACTS / f"{NAME}.sol")],
        output_values=["abi", "bin"],
        solc_version=SOLC_VERSION,
        evm_version="cancun",
        optimize=True,
        optimize_runs=200,
        import_remappings=["@openzeppelin/=node_modules/@openzeppelin/"],  # relative to base_path: solc dislikes drive letters
        base_path=str(CONTRACTS),
        allow_paths=str(CONTRACTS),
    )
    compiled = out[next(k for k in out if k.endswith(f":{NAME}"))]
    artifact = {"contractName": NAME, "solc": SOLC_VERSION, "abi": compiled["abi"], "bytecode": "0x" + compiled["bin"]}
    target = CONTRACTS / "build" / f"{NAME}.json"
    target.write_text(json.dumps(artifact, indent=2))
    print(f"Wrote {target.relative_to(ROOT)} ({len(compiled['bin']) // 2} bytes of bytecode)")


if __name__ == "__main__":
    compile_token()
