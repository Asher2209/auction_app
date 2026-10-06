"""Admin routes for blockchain card token minting"""

from flask import abort, flash, jsonify, redirect, render_template, request, url_for, current_app
from flask_login import current_user

from ...extensions import db
from ...models import BlockchainAsset, CollectibleCard, CollectibleVerification
from ...services import blockchain_minting_service as bm_service, blockchain_service as bc
from ...utils import role_required
from . import bp


@bp.route("/tokens/mint/<int:blockchain_asset_id>", methods=["GET", "POST"])
@role_required("admin")
def mint_token(blockchain_asset_id):
    """Initiate token minting for a card"""
    blockchain_asset = BlockchainAsset.query.get_or_404(blockchain_asset_id)
    collectible_card = blockchain_asset.collectible_card
    seller = collectible_card.product.seller
    
    if request.method == "POST":
        try:
            # Get minter wallet
            minter_wallet = request.form.get("minter_wallet", "").strip()
            if not minter_wallet:
                flash("Minter wallet address required", "danger")
            else:
                # Normalize wallet
                minter_wallet = bc.normalize_wallet(minter_wallet)
                
                # Prepare mint transaction
                tx_data = bm_service.initiate_mint(blockchain_asset, minter_wallet)
                
                # Return transaction data for signing
                return render_template(
                    'admin/mint_transaction.html',
                    blockchain_asset=blockchain_asset,
                    collectible_card=collectible_card,
                    tx_data=tx_data,
                    seller=seller
                )
        except bm_service.MintError as e:
            flash(f"Error: {e.message}", "danger")
        except Exception as e:
            flash(f"Error preparing mint: {str(e)}", "danger")
    
    return render_template(
        'admin/mint_prepare.html',
        blockchain_asset=blockchain_asset,
        collectible_card=collectible_card,
        seller=seller,
        crypto_enabled=bc.crypto_enabled()
    )


@bp.route("/tokens/mint/<int:blockchain_asset_id>/submit", methods=["POST"])
@role_required("admin")
def submit_mint(blockchain_asset_id):
    """Submit minting transaction hash"""
    blockchain_asset = BlockchainAsset.query.get_or_404(blockchain_asset_id)
    
    tx_hash = request.form.get("tx_hash", "").strip()
    
    try:
        bm_service.submit_mint(blockchain_asset, tx_hash)
        flash(f"Mint transaction submitted. Token minting in progress.", "success")
    except bm_service.MintError as e:
        flash(f"Error: {e.message}", "danger")
    except Exception as e:
        flash(f"Error submitting mint: {str(e)}", "danger")
    
    return redirect(url_for('admin.token_status', blockchain_asset_id=blockchain_asset_id))


@bp.route("/tokens/status/<int:blockchain_asset_id>", methods=["GET"])
@role_required("admin")
def token_status(blockchain_asset_id):
    """Check token minting/transfer status"""
    blockchain_asset = BlockchainAsset.query.get_or_404(blockchain_asset_id)
    collectible_card = blockchain_asset.collectible_card
    
    # Verify current status
    result = bm_service.verify_mint(blockchain_asset)
    
    # Update if confirmed
    if result.get("status") == "confirmed":
        # Extract token ID from contract (would need to be done separately in real implementation)
        # For now, use predictable ID based on asset
        token_id = blockchain_asset.id + 1000
        bm_service.complete_mint(
            blockchain_asset,
            token_id,
            result.get("block_number")
        )
        flash(f"Token minting confirmed! Token ID: {token_id}", "success")
    
    return render_template(
        'admin/token_status.html',
        blockchain_asset=blockchain_asset,
        collectible_card=collectible_card,
        verification_result=result
    )


@bp.route("/api/tokens/verify/<int:blockchain_asset_id>", methods=["GET"])
@role_required("admin")
def api_verify_mint(blockchain_asset_id):
    """API endpoint to check mint status"""
    blockchain_asset = BlockchainAsset.query.get_or_404(blockchain_asset_id)
    
    result = bm_service.verify_mint(blockchain_asset)
    
    return jsonify(result)
