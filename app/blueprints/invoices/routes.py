import time

from flask import Response, abort, render_template, request
from flask_login import current_user, login_required

from ...extensions import db
from ...models import Payment
from ...services import blockchain_service as bc
from ...services import invoice_service as inv
from . import bp

CHECK_TTL_SECONDS = 60
_check_cache = {}  # invoice id -> (expires_at, result). The public page must not be a way to hammer the RPC node.


@bp.route("/invoices/<int:auction_id>/download")
@login_required
def download(auction_id):
    """The PDF, for the buyer, the seller or an admin. 404 for anyone else, so invoices cannot be probed."""
    payment = Payment.query.filter_by(auction_id=auction_id).first()
    if payment is None or payment.payment_status != "successful":
        abort(404)
    if not (current_user.role == "admin" or current_user.id in (payment.buyer_id, payment.auction.product.seller_id)):
        abort(404)
    invoice = inv.create_for_payment(payment, announce=False)  # also covers payments made before invoices existed
    db.session.commit()
    return Response(
        inv.render_pdf(invoice), mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.number}.pdf"', "Cache-Control": "private, no-store"})


def _chain_check(invoice):
    now = time.monotonic()
    hit = _check_cache.get(invoice.id)
    if hit and hit[0] > now:
        return hit[1]
    result = bc.recheck(invoice.payment)
    if len(_check_cache) > 500:
        _check_cache.clear()
    _check_cache[invoice.id] = (now + CHECK_TTL_SECONDS, result)
    return result


@bp.route("/verify/<token>")
def verify(token):
    """Public page the invoice QR code points at. Shows only what is needed to confirm the invoice is genuine."""
    invoice = inv.invoice_from_token(token)
    if invoice is None:
        abort(404)
    payment = invoice.payment
    on_chain = inv.is_blockchain_verified(payment)
    checked = request.args.get("check") == "1" and on_chain
    return render_template(
        "invoices/verify.html", invoice=invoice, payment=payment, auction=payment.auction,
        product=payment.auction.product, method=inv.method_label(payment), on_chain=on_chain,
        crypto=payment.crypto if on_chain else None, checked=checked,
        result=_chain_check(invoice) if checked else None,
        explorer=bc.explorer_url(payment.crypto.transaction_hash) if on_chain else None)
