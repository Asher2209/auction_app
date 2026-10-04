"""Simulated (conventional) payments. No real money moves and no card data is kept.

The "gateway" is deterministic so every outcome can be demonstrated and tested:

  Card    4242 4242 4242 4242 -> success       4000 0000 0000 0002 -> declined
          4000 0000 0000 9995 -> insufficient  4000 0000 0000 3220 -> pending (settles later)
          any other Luhn-valid number -> success
  UPI     id containing "fail" -> failed, containing "pending" -> pending, otherwise success
  Wallet  mobile ending 0000 -> failed, ending 1111 -> pending, otherwise success

Card numbers and CVVs are validated and then discarded. Only a masked reference is stored.

State changes are compare-and-set updates, so a double submit or two tabs can never pay twice.
"""
import re
import secrets
from datetime import timedelta

from flask import current_app
from sqlalchemy import and_, or_, update

from ..extensions import db
from ..models import Payment, utcnow
from . import invoice_service
from .notifications import notify

KINDS = ("card", "upi", "wallet")
WALLETS = ("Demo Wallet", "Test Pay")

CARD_OUTCOMES = {
    "4000000000000002": ("failed", "Your card was declined by the (simulated) bank."),
    "4000000000009995": ("failed", "Insufficient funds on the (simulated) card."),
    "4000000000003220": ("pending", None),
}
UPI_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}@[A-Za-z]{2,32}$")
EXPIRY_RE = re.compile(r"^(0[1-9]|1[0-2])\s*/\s*([0-9]{2})$")


class PaymentError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _money(value):
    return f"{current_app.config['CURRENCY_SYMBOL']}{value:,.2f}"


# ---- input checks (also used by the forms) --------------------------------------
def luhn_ok(number):
    digits = [int(c) for c in number]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def clean_card_number(raw):
    """Digits only, 12-19 long and Luhn-valid; otherwise None."""
    digits = re.sub(r"[ -]", "", raw or "")
    if re.fullmatch(r"[0-9]{12,19}", digits) and luhn_ok(digits):
        return digits
    return None


def expiry_ok(raw, now=None):
    m = EXPIRY_RE.match(raw or "")
    if not m:
        return False
    now = now or utcnow()
    return (2000 + int(m.group(2)), int(m.group(1))) >= (now.year, now.month)  # valid through the end of that month


# ---- the simulated gateway --------------------------------------------------------
def simulate_gateway(kind, data):
    """Return (outcome, failure_reason, masked_reference). Outcome: success / failed / pending."""
    if kind == "card":
        pan = data["card_number"]
        outcome, reason = CARD_OUTCOMES.get(pan, ("success", None))
        return outcome, reason, f"Card **** {pan[-4:]}"
    if kind == "upi":
        upi = data["upi_id"].lower()
        local, _, handle = upi.partition("@")
        ref = f"UPI {local[:2]}***@{handle}"
        if "fail" in upi:
            return "failed", "The (simulated) UPI request was declined.", ref
        return ("pending" if "pending" in upi else "success"), None, ref
    if kind == "wallet":
        mobile = data["mobile"]
        ref = f"{data['provider']} ****{mobile[-4:]}"
        if mobile.endswith("0000"):
            return "failed", "The (simulated) wallet balance was too low.", ref
        return ("pending" if mobile.endswith("1111") else "success"), None, ref
    raise PaymentError("Unknown payment type.", 404)


# ---- state transitions -----------------------------------------------------------
def on_success(payment, now):
    auction = payment.auction
    title = auction.product.title
    amount = _money(payment.amount)
    notify(payment.buyer_id, "Payment successful", f'Your payment of {amount} for "{title}" was successful.',
           url=f"/payments/{auction.id}", email=True)
    notify(auction.product.seller_id, "Payment received", f'{payment.buyer.name} paid {amount} for "{title}".',
           url=f"/seller/products/{auction.product_id}", email=True)
    invoice_service.create_for_payment(payment, now)  # same transaction as the payment itself


def pay_simulated(auction_id, buyer, kind, data, now=None):
    """Run one simulated payment attempt for the winning buyer. Returns the fresh Payment."""
    now = now or utcnow()
    payment = Payment.query.filter_by(auction_id=auction_id, buyer_id=buyer.id).first()
    if payment is None:
        raise PaymentError("No payment is due for this auction.", 404)
    if payment.payment_status == "successful":
        raise PaymentError("This auction has already been paid for.", 409)
    if not payment.awaiting_payment:
        raise PaymentError("Your payment is still being processed. Please wait for it to finish.", 409)

    outcome, reason, reference = simulate_gateway(kind, data)
    status = {"success": "successful", "failed": "failed", "pending": "pending"}[outcome]
    values = {
        "payment_method": "simulated", "method_detail": kind, "reference": reference,
        "gateway_ref": "SIM-" + secrets.token_hex(6).upper(), "failure_reason": reason,
        "attempts": Payment.attempts + 1, "payment_status": status,
        "payment_date": now if outcome == "success" else None,
        "settle_at": now + timedelta(seconds=current_app.config["SIMULATED_SETTLE_SECONDS"]) if outcome == "pending" else None,
    }
    # Only proceed if the payment is still awaiting payment (guards double submits and parallel tabs).
    claimed = db.session.execute(
        update(Payment).where(
            Payment.id == payment.id, Payment.buyer_id == buyer.id,
            or_(Payment.payment_status == "failed",
                and_(Payment.payment_status == "pending", Payment.payment_method.is_(None))),
        ).values(**values),
        execution_options={"synchronize_session": False}).rowcount
    if claimed != 1:
        db.session.rollback()
        raise PaymentError("This payment was already submitted. Refresh the page to see its status.", 409)

    db.session.expire_all()
    payment = db.session.get(Payment, payment.id)
    title = payment.auction.product.title
    if outcome == "success":
        on_success(payment, now)
    elif outcome == "failed":
        notify(buyer.id, "Payment failed", f'Your payment for "{title}" failed: {reason} You can try again.',
               url=f"/payments/{auction_id}")
    else:
        notify(buyer.id, "Payment processing", f'Your payment for "{title}" is being processed.',
               url=f"/payments/{auction_id}")
    db.session.commit()
    return payment


def settle_due(now=None):
    """Settle gateway-pending simulated payments whose time has come (they succeed). Returns how many."""
    now = now or utcnow()
    ids = [i for (i,) in db.session.query(Payment.id).filter(
        Payment.payment_status == "pending", Payment.payment_method == "simulated",
        Payment.settle_at.isnot(None), Payment.settle_at <= now)]
    settled = 0
    for pid in ids:
        claimed = db.session.execute(
            update(Payment).where(Payment.id == pid, Payment.payment_status == "pending", Payment.settle_at <= now)
            .values(payment_status="successful", payment_date=now, settle_at=None, failure_reason=None),
            execution_options={"synchronize_session": False}).rowcount
        if claimed != 1:
            db.session.rollback()
            continue
        db.session.expire_all()
        on_success(db.session.get(Payment, pid), now)
        db.session.commit()
        settled += 1
    return settled


def pending_total():
    """Number of payments not yet successful (for the admin dashboard)."""
    return Payment.query.filter(Payment.payment_status != "successful").count()


def revenue_total():
    from sqlalchemy import func
    return db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.payment_status == "successful").scalar()
