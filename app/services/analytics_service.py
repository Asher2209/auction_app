"""Admin analytics. Everything here is read-only aggregation over the existing tables.

Definitions (also shown on the page, so the numbers can be explained):
* Revenue          = sum of SUCCESSFUL payments, bucketed by payment date.
* Popular category = number of bids placed on auctions in that category (demand).
* Top products     = the highest-value paid sales.  Top sellers = paid sales value per seller.
* Active buyers    = buyers ranked by number of bids placed.
* Payment methods  = successful payments by method (Card / UPI / Wallet / Cryptocurrency).

Month bucketing is done in Python so the same code runs on SQLite and MySQL.
"""
from decimal import Decimal

from sqlalchemy import func

from .. import timeutil
from ..extensions import db
from ..models import Auction, Bid, Category, CryptoPayment, Payment, Product, User, utcnow

ALLOWED_MONTHS = (3, 6, 12, 24)
DEFAULT_MONTHS = 12
TOP_N = 8
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Fixed entity order: each of these keeps the same colour on every chart and every filter setting.
AUCTION_STATUSES = (("active", "Active"), ("scheduled", "Scheduled"), ("closed", "Completed"), ("cancelled", "Cancelled"))
PAYMENT_METHODS = (("card", "Card"), ("upi", "UPI"), ("wallet", "Wallet"), ("crypto", "Cryptocurrency"))


def parse_months(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MONTHS
    return value if value in ALLOWED_MONTHS else DEFAULT_MONTHS


def month_range(months, now):
    """[(year, month), ...] oldest first, ending with the month of `now`."""
    out, y, m = [], now.year, now.month
    for _ in range(months):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def _month(when):
    local = timeutil.to_local(when)
    return local.year, local.month


def _label(ym):
    return f"{MONTH_NAMES[ym[1] - 1]} {ym[0]}"


def _money(value):
    return round(float(value or 0), 2)


def _method_key(payment):
    if payment.payment_method == "crypto":
        return "crypto"
    return payment.method_detail if payment.method_detail in ("card", "upi", "wallet") else "card"


def build(months=DEFAULT_MONTHS, now=None):
    """All chart datasets, JSON-ready."""
    now = now or utcnow()
    keys = month_range(months, timeutil.to_local(now))  # months are the site zone's calendar months
    labels = [_label(k) for k in keys]
    index = {k: i for i, k in enumerate(keys)}
    start = keys[0]
    from datetime import datetime
    window_start = timeutil.from_local(datetime(start[0], start[1], 1))

    # ---- revenue per month, split simulated vs crypto -----------------------------------
    simulated, crypto, eth = [0.0] * months, [0.0] * months, [0.0] * months
    paid_rows = (db.session.query(Payment.payment_date, Payment.amount, Payment.payment_method, CryptoPayment.amount)
                 .outerjoin(CryptoPayment, CryptoPayment.payment_id == Payment.id)
                 .filter(Payment.payment_status == "successful", Payment.payment_date >= window_start).all())
    for when, amount, method, eth_amount in paid_rows:
        i = index.get(_month(when))
        if i is None:  # a payment dated in the future of `now`
            continue
        if method == "crypto":
            crypto[i] += float(amount)
            eth[i] += float(eth_amount or 0)
        else:
            simulated[i] += float(amount)

    # ---- auctions started per month ----------------------------------------------------------
    per_month = [0] * months
    for (when,) in db.session.query(Auction.start_time).filter(Auction.start_time >= window_start,
                                                                Auction.status != "cancelled"):
        i = index.get(_month(when))
        if i is not None:
            per_month[i] += 1

    # ---- active vs completed (and the other states) ----------------------------------------------
    counts = dict(db.session.query(Auction.status, func.count(Auction.id)).group_by(Auction.status).all())
    status = [{"key": k, "label": name, "value": counts.get(k, 0)} for k, name in AUCTION_STATUSES]

    # ---- popular categories (by bids) ------------------------------------------------------------
    cat_rows = (db.session.query(Category.name, func.count(func.distinct(Bid.id)), func.count(func.distinct(Auction.id)))
                .join(Product, Product.category_id == Category.id)
                .join(Auction, Auction.product_id == Product.id)
                .outerjoin(Bid, Bid.auction_id == Auction.id)
                .group_by(Category.id, Category.name)
                .order_by(func.count(func.distinct(Bid.id)).desc(), func.count(func.distinct(Auction.id)).desc(), Category.name)
                .limit(TOP_N).all())
    categories = [{"label": n, "value": bids, "auctions": a} for n, bids, a in cat_rows]

    # ---- top products / sellers (paid sales) ---------------------------------------------------------
    prod_rows = (db.session.query(Product.title, Payment.amount, User.name)
                 .join(Auction, Auction.product_id == Product.id).join(Payment, Payment.auction_id == Auction.id)
                 .join(User, User.id == Product.seller_id)
                 .filter(Payment.payment_status == "successful")
                 .order_by(Payment.amount.desc(), Product.title).limit(TOP_N).all())
    top_products = [{"label": t, "value": _money(a), "seller": s} for t, a, s in prod_rows]

    seller_rows = (db.session.query(User.name, func.sum(Payment.amount), func.count(Payment.id))
                   .join(Product, Product.seller_id == User.id).join(Auction, Auction.product_id == Product.id)
                   .join(Payment, Payment.auction_id == Auction.id)
                   .filter(Payment.payment_status == "successful")
                   .group_by(User.id, User.name).order_by(func.sum(Payment.amount).desc(), User.name).limit(TOP_N).all())
    top_sellers = [{"label": n, "value": _money(total), "sales": c} for n, total, c in seller_rows]

    # ---- most active buyers ------------------------------------------------------------------------------
    buyer_rows = (db.session.query(User.name, func.count(Bid.id), func.count(func.distinct(Bid.auction_id)))
                  .join(Bid, Bid.buyer_id == User.id).group_by(User.id, User.name)
                  .order_by(func.count(Bid.id).desc(), User.name).limit(TOP_N).all())
    active_buyers = [{"label": n, "value": b, "auctions": a} for n, b, a in buyer_rows]

    # ---- payment methods (successful payments) ---------------------------------------------------------------
    by_method = {k: 0 for k, _ in PAYMENT_METHODS}
    for payment in Payment.query.filter_by(payment_status="successful").all():
        by_method[_method_key(payment)] += 1
    methods = [{"key": k, "label": name, "value": by_method[k]} for k, name in PAYMENT_METHODS]

    # ---- crypto statistics -------------------------------------------------------------------------------------
    cstatus = dict(db.session.query(CryptoPayment.status, func.count(CryptoPayment.id)).group_by(CryptoPayment.status).all())
    confirmed = (db.session.query(func.count(CryptoPayment.id), func.coalesce(func.sum(CryptoPayment.amount), 0),
                                  func.coalesce(func.sum(Payment.amount), 0), func.avg(CryptoPayment.confirmations))
                 .join(Payment, Payment.id == CryptoPayment.payment_id).filter(CryptoPayment.status == "confirmed").one())
    n_ok, n_fail = cstatus.get("confirmed", 0), cstatus.get("failed", 0)
    crypto_stats = {
        "confirmed": n_ok, "pending": cstatus.get("pending", 0), "failed": n_fail,
        "eth_total": round(float(Decimal(confirmed[1] or 0)), 6), "inr_total": _money(confirmed[2]),
        "avg_confirmations": round(float(confirmed[3]), 1) if confirmed[3] is not None else None,
        "success_rate": round(100 * n_ok / (n_ok + n_fail), 1) if (n_ok + n_fail) else None,
    }

    # ---- headline numbers -----------------------------------------------------------------------------------------
    total_paid, paid_count = db.session.query(func.coalesce(func.sum(Payment.amount), 0), func.count(Payment.id)).filter(
        Payment.payment_status == "successful").one()
    kpis = {"revenue": _money(total_paid), "paid_sales": paid_count,
            "average_sale": _money(Decimal(total_paid) / paid_count) if paid_count else 0.0}

    return {
        "months": months, "labels": labels, "kpis": kpis,
        "revenue": {"simulated": [round(v, 2) for v in simulated], "crypto": [round(v, 2) for v in crypto]},
        "auctions_per_month": per_month, "status": status, "categories": categories,
        "top_products": top_products, "top_sellers": top_sellers, "active_buyers": active_buyers,
        "methods": methods, "crypto": crypto_stats, "eth_per_month": [round(v, 6) for v in eth],
        "empty": {"revenue": not any(simulated) and not any(crypto), "auctions": not any(per_month)},
    }
