"""The documentation must not drift away from the code."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = re.compile(r"`(tests/test_\w+\.py)::(test_\w+)`")


def test_every_test_named_in_the_matrix_exists():
    text = (ROOT / "docs" / "TEST_MATRIX.md").read_text(encoding="utf-8")
    refs = REF.findall(text)
    assert len(refs) >= 100
    missing = []
    for path, name in refs:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        if not any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.walk(tree)):
            missing.append(f"{path}::{name}")
    assert missing == []


def test_the_matrix_covers_every_section_of_the_briefs_test_plan():
    text = (ROOT / "docs" / "TEST_MATRIX.md").read_text(encoding="utf-8")
    for heading in ("## Authentication", "## Seller", "## Buyer", "## Auction", "## Payment", "## Blockchain", "## Security", "## Not covered"):
        assert heading in text
    for item in ("Registration", "Password reset", "Image upload", "Watchlist", "Simultaneous bids", "Auction extension", "Pending payment",
                 "Payment mismatch", "Unconfirmed transaction", "SQL injection", "File upload validation"):
        assert item in text, item


def test_every_environment_variable_is_documented():
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    names = set(re.findall(r'os\.environ\.get\(\s*"([A-Z_]+)"', config))
    assert len(names) >= 20
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    undocumented = [n for n in sorted(names) if f"`{n}`" not in readme]
    not_in_example = [n for n in sorted(names) if n not in env_example]
    assert undocumented == [] and not_in_example == []


def test_readme_states_what_is_not_verified():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for must_say in ("MySQL", "Sepolia", "Not tested", "synthetic"):
        assert must_say in readme


def test_the_committed_contract_abi_matches_a_fresh_compile_of_its_source():
    """If someone edits AuctionPayment.sol but forgets scripts/compile_contract.py, the app would talk to the old ABI."""
    import json

    import pytest
    solcx = pytest.importorskip("solcx")
    if "0.8.24" not in [str(v) for v in solcx.get_installed_solc_versions()]:
        pytest.skip("solc 0.8.24 is not installed here (run scripts/compile_contract.py once to install it)")
    committed = json.loads((ROOT / "contracts" / "build" / "AuctionPayment.json").read_text())
    fresh = solcx.compile_source((ROOT / "contracts" / "AuctionPayment.sol").read_text(), output_values=["abi", "bin"], solc_version="0.8.24",
                                 optimize=True, optimize_runs=200)
    (compiled,) = fresh.values()
    canon = lambda abi: sorted(json.dumps(x, sort_keys=True) for x in abi)  # noqa: E731
    assert canon(compiled["abi"]) == canon(committed["abi"])
    assert committed["bytecode"].startswith("0x") and len(committed["bytecode"]) > 200
