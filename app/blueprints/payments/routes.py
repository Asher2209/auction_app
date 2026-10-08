from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from ...extensions import db
from ...models import Payment, utcnow
from ...ratelimit import limited
from ...services import blockchain_service as bc
from ...services import card_settlement_service as css
from ...services import ownership_transfer_service as ots
from ...services import payment_service as ps
from ...services.payment_service import PaymentError
from ...utils import role_required
from . import bp
from .forms import FORMS


def _own_payment_or_404(auction_id):
    # 404 (not 403) for other people's auctions, so they cannot be probed
    payment = Payment.query.filter_by(auction_id=auction_id, buyer_id=current_user.id).first()
    if payment is None:
        abort(404)
    return payment


def _crypto_context(payment):
    """What the crypto tab needs to render. Empty/disabled when crypto is not configured."""
    if css.applies(payment):
        return css.pay_context(payment)
    if not bc.crypto_enabled():
        return {"enabled": False}
    wei, eth, rate = bc.quote(payment.amount)
    seller = payment.auction.product.seller
    row = payment.crypto
    return {
        "enabled": True, "eth": format(eth, "f"), "rate": f"{rate:,.2f}", "seller_wallet": seller.verified_wallet,
        "chain_name": current_app.config["CHAIN_NAME"], "chain_id_hex": hex(current_app.config["CHAIN_ID"]),
        "required": current_app.config["CONFIRMATIONS_REQUIRED"],
        "tx_hash": row.transaction_hash if row else None,
        "explorer": bc.explorer_url(row.transaction_hash) if row else None,
        "confirmations": row.confirmations if row else 0,
        "dev_wallet": bool(current_app.config.get("LOCAL_CHAIN")),
    }


def _ownership(payment):
    """The recorded token transfer for a completed card sale, or None."""
    if payment.payment_status != "successful" or not css.applies(payment):
        return None
    transfer = ots.transfer_for_payment(payment)
    if transfer is None:
        return None
    return {"transfer": transfer, "asset": transfer.blockchain_asset, "explorer": bc.explorer_url(transfer.transaction_hash)}


def _render(payment, active="card", forms=None):
    forms = forms or {k: cls(formdata=None) for k, cls in FORMS.items()}
    return render_template("payments/pay.html", payment=payment, auction=payment.auction,
                           product=payment.auction.product, forms=forms, active=active,
                           crypto=_crypto_context(payment), ownership=_ownership(payment))


@bp.route("/<int:auction_id>")
@role_required("buyer")
def pay_page(auction_id):
    payment = _own_payment_or_404(auction_id)
    ps.settle_due()  # a pending payment may be due to settle
    db.session.refresh(payment)
    return _render(payment)


@bp.route("/<int:auction_id>/status")
@role_required("buyer")
def status(auction_id):
    payment = _own_payment_or_404(auction_id)
    ps.settle_due()
    db.session.refresh(payment)
    body = {"status": payment.payment_status, "processing": payment.processing, "method": payment.payment_method}
    if payment.payment_method == "crypto" and payment.crypto:
        try:
            bc.verify_payment(payment)  # check the chain now rather than waiting for the scheduler
        except bc.CryptoError as e:
            body["error"] = e.message
        except Exception:
            db.session.rollback()
            current_app.logger.warning("Crypto status check failed", exc_info=True)
            body["error"] = "Could not reach the blockchain right now. Retrying."
        db.session.refresh(payment)
        row = payment.crypto
        body.update(status=payment.payment_status, processing=payment.processing, confirmations=row.confirmations or 0,
                    required=current_app.config["CONFIRMATIONS_REQUIRED"], tx_hash=row.transaction_hash,
                    reason=row.failure_reason if payment.payment_status == "failed" else None)
    return jsonify(body)


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.route("/<int:auction_id>/crypto/prepare", methods=["POST"])
@role_required("buyer")
@limited("crypto", 20, 60, by="user")
def crypto_prepare(auction_id):
    payment = _own_payment_or_404(auction_id)
    body = _json_body()
    if body.get("accept_terms") is not True:  # exactly JSON true: the box on the page, not a truthy string or number
        return jsonify(ok=False, error="Please tick the box to confirm you have read the Refund Policy: "
                                       "a blockchain payment cannot be reversed."), 400
    try:
        return jsonify(ok=True, **bc.prepare(payment, body.get("wallet_address")))
    except bc.CryptoError as e:
        return jsonify(ok=False, error=e.message), e.status


@bp.route("/<int:auction_id>/crypto/submit", methods=["POST"])
@role_required("buyer")
@limited("crypto", 20, 60, by="user")
def crypto_submit(auction_id):
    payment = _own_payment_or_404(auction_id)
    try:
        payment = bc.submit(payment, _json_body().get("tx_hash"))
        try:
            bc.verify_payment(payment)  # best effort right away; the poller/scheduler follows up
        except Exception:
            db.session.rollback()
            current_app.logger.warning("Immediate crypto verification failed", exc_info=True)
        return jsonify(ok=True)
    except bc.CryptoError as e:
        return jsonify(ok=False, error=e.message), e.status


@bp.route("/<int:auction_id>/pay/<kind>", methods=["POST"])
@role_required("buyer")
@limited("pay", 20, 60, by="user")
def pay(auction_id, kind):
    if kind not in FORMS:
        abort(404)
    payment = _own_payment_or_404(auction_id)
    forms = {k: cls(formdata=None) for k, cls in FORMS.items()}
    form = FORMS[kind]()
    forms[kind] = form
    if not form.validate_on_submit():
        for name in ("card_number", "cvv"):  # never send card details back to the browser
            if hasattr(form, name):
                getattr(form, name).data = ""
        return _render(payment, active=kind, forms=forms), 400

    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in form.data.items() if k not in ("csrf_token", "accept")}
    if kind == "card":
        data["card_number"] = ps.clean_card_number(data["card_number"])
    try:
        result = ps.pay_simulated(auction_id, current_user, kind, data, now=utcnow())
    except PaymentError as e:
        flash(e.message, "danger" if e.status != 409 else "warning")
        return redirect(url_for("payments.pay_page", auction_id=auction_id))

    if result.payment_status == "successful":
        flash("Payment successful. Thank you!", "success")
    elif result.payment_status == "failed":
        flash(f"Payment failed: {result.failure_reason} You can try again.", "danger")
    else:
        flash("Your payment is being processed. This page will update when it completes.", "info")
    return redirect(url_for("payments.pay_page", auction_id=auction_id))
