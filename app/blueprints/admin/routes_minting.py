"""Admin pages for registering platform-verified cards on the blockchain (minting).

The admin's wallet (MetaMask) signs the mint. The server prepares the transaction and later verifies it on
the chain; it never holds a private key.
"""
from flask import abort, jsonify, render_template, request

from ...extensions import db
from ...models import BlockchainAsset
from ...services import blockchain_minting_service as bm
from ...services import blockchain_service as bc
from ...utils import role_required
from . import bp

TOKEN_STATUSES = ("all", "draft", "minting", "minted")


def _asset_or_404(asset_id):
    asset = db.session.get(BlockchainAsset, asset_id)
    if asset is None:
        abort(404)
    return asset


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.route("/tokens")
@role_required("admin")
def tokens():
    status = request.args.get("status", "all")
    if status not in TOKEN_STATUSES:
        status = "all"
    query = BlockchainAsset.query
    if status != "all":
        query = query.filter(BlockchainAsset.status == status)
    page = query.order_by(BlockchainAsset.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=15, error_out=False)
    return render_template("admin/tokens.html", page=page, status=status, statuses=TOKEN_STATUSES)


@bp.route("/tokens/<int:asset_id>")
@role_required("admin")
def token_detail(asset_id):
    asset = _asset_or_404(asset_id)
    return render_template("admin/token_detail.html", asset=asset, card=asset.collectible_card,
                           chain=bm.chain_info(), chain_ready=bm.chain_ready(),
                           tx_url=bc.explorer_url(asset.mint_transaction_hash))


@bp.route("/tokens/<int:asset_id>/mint/prepare", methods=["POST"])
@role_required("admin")
def token_mint_prepare(asset_id):
    asset = _asset_or_404(asset_id)
    try:
        prep = bm.initiate_mint(asset, _json_body().get("wallet_address"))
    except bm.MintError as e:
        return jsonify(ok=False, error=e.message), e.status
    return jsonify(ok=True, **prep)


@bp.route("/tokens/<int:asset_id>/mint/submit", methods=["POST"])
@role_required("admin")
def token_mint_submit(asset_id):
    asset = _asset_or_404(asset_id)
    try:
        bm.submit_mint(asset, _json_body().get("tx_hash"))
    except bm.MintError as e:
        return jsonify(ok=False, error=e.message), e.status
    return jsonify(ok=True)


@bp.route("/tokens/<int:asset_id>/verify", methods=["POST"])
@role_required("admin")
def token_verify(asset_id):
    """Read the chain and, if the mint is genuine and confirmed, record the real token ID."""
    return jsonify(ok=True, **bm.confirm_mint(_asset_or_404(asset_id)))
