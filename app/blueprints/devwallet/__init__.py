"""DEVELOPMENT ONLY. Registered only when LOCAL_CHAIN=1 (an in-memory test chain with fake ETH).

It stands in for MetaMask so the whole crypto flow can be demonstrated without a browser extension or
a funded Sepolia wallet. It can only spend from a built-in demo account, only on the in-memory chain,
and only towards the payment contract. It does not exist in a normal (Sepolia) deployment.
"""
from flask import Blueprint

bp = Blueprint("devwallet", __name__, url_prefix="/dev-wallet")

from . import routes  # noqa: E402,F401
