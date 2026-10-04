from flask import abort, current_app, jsonify, render_template, request
from flask_login import login_required
from web3 import Web3

from ...services import blockchain_service as bc
from . import bp

BUYER_INDEX, SELLER_INDEX = 1, 2  # which built-in test accounts act as the demo buyer / seller wallets


def _chain():
    w3 = bc.get_web3()
    accounts = current_app.extensions.get("local_chain_accounts")
    if w3 is None or not accounts:
        abort(404)
    return w3, accounts


@bp.route("/")
@login_required
def index():
    w3, accounts = _chain()
    rows = [{"address": a, "eth": Web3.from_wei(w3.eth.get_balance(a), "ether"),
             "role": {BUYER_INDEX: "Demo buyer wallet", SELLER_INDEX: "Demo seller payout wallet"}.get(i, "")}
            for i, a in enumerate(accounts)]
    return render_template("devwallet/index.html", rows=rows, block=w3.eth.block_number,
                           chain_id=w3.eth.chain_id, contract=current_app.config["CONTRACT_ADDRESS"])


@bp.route("/account")
@login_required
def account():
    w3, accounts = _chain()
    return jsonify(address=accounts[BUYER_INDEX], chain_id=hex(w3.eth.chain_id))


@bp.route("/send", methods=["POST"])
@login_required
def send():
    """Sign and send a transaction from the demo buyer wallet, to the payment contract only."""
    w3, accounts = _chain()
    tx = (request.get_json(silent=True) or {}).get("tx") or {}
    contract = current_app.config["CONTRACT_ADDRESS"]
    if (tx.get("from") or "").lower() != accounts[BUYER_INDEX].lower() or (tx.get("to") or "").lower() != contract.lower():
        return jsonify(error="The demo wallet only sends from its own account to the payment contract."), 400
    try:
        tx_hash = w3.eth.send_transaction({
            "from": accounts[BUYER_INDEX], "to": contract,
            "value": int(tx.get("value", "0x0"), 16), "data": tx.get("data", "0x"),
        })
    except Exception as e:  # e.g. the contract reverts: behave like a wallet that refuses to send
        return jsonify(error=f"Transaction rejected: {str(e)[:120]}"), 400
    return jsonify(hash=Web3.to_hex(tx_hash))  # always "0x"-prefixed


@bp.route("/mine", methods=["POST"])
@login_required
def mine():
    w3, _ = _chain()
    blocks = max(1, min(int((request.get_json(silent=True) or {}).get("blocks", 1)), 20))
    w3.provider.ethereum_tester.mine_blocks(blocks)
    return jsonify(block=w3.eth.block_number)
