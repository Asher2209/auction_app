"""The eleven admin reports as data: each one is a definition (columns, filters) plus a query function.

The same definition drives the on-screen table, the PDF and the Excel export (see report_export.py), so
adding a report means writing one function and one entry in REPORTS.

Conventions
* Times are UTC. A date range is inclusive of both days.
* Money is INR. Rows are tuples aligned with the report's columns.
* Every query is an aggregate or a join (no per-row queries), and results are capped at MAX_ROWS.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import aliased

from ..extensions import db
from ..models import (
    Auction, Bid, Category, CryptoPayment, Invoice, Payment, Product, Review, User, Winner, utcnow,
)

MAX_ROWS = 5000
TOP_PRODUCTS = 100
DEFAULT_DAYS = 30
MAX_RANGE_DAYS = 36600  # 100 years: only a guard against absurd input; "All time" starts in 2000
STATUS_CHOICES = ("all", "successful", "pending", "failed")
AUCTION_STATUS = {"scheduled": "Scheduled", "active": "Active", "closed": "Completed", "cancelled": "Cancelled"}

Seller = aliased(User)
Buyer = aliased(User)
Bidder = aliased(User)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"  # text int money eth datetime date rating pct mono
    weight: float = 1.0  # relative width in the PDF


@dataclass(frozen=True)
class Params:
    start: datetime | None = None  # inclusive
    end: datetime | None = None  # exclusive
    day: date | None = None
    status: str = "all"

    @property
    def last_day(self):
        return (self.end - timedelta(days=1)).date() if self.end else None


@dataclass
class Data:
    rows: list
    summary: list = field(default_factory=list)  # [(label, value, kind)]
    truncated: bool = False


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    description: str
    columns: tuple
    fetch: object
    filter: str = "range"  # range | day | none
    filter_label: str = ""  # what the date range applies to
    default_days: int | None = DEFAULT_DAYS  # None: all time unless the user picks a range
    statuses: bool = False
    pdf_skip: tuple = ()  # columns left out of the (narrower) PDF; the Excel file always has them all


# ---- parameters ------------------------------------------------------------------------------
def parse_date(text):
    return datetime.strptime(text.strip(), "%Y-%m-%d").date()


def parse_params(report, args, now=None):
    """Return (Params, errors). Bad input never raises: it produces a message and a safe default."""
    now = now or utcnow()
    today = now.date()
    errors, status = [], "all"
    if report.statuses:
        status = args.get("status", "all")
        if status not in STATUS_CHOICES:
            errors.append("Unknown status filter; showing all.")
            status = "all"

    def read(name):
        raw = (args.get(name) or "").strip()
        if not raw:
            return None
        try:
            return parse_date(raw)
        except ValueError:
            errors.append(f"'{name}' must be a date like 2026-10-31.")
            return None

    if report.filter == "day":
        day = read("day") or today
        return Params(datetime.combine(day, datetime.min.time()), datetime.combine(day + timedelta(days=1), datetime.min.time()), day, status), errors
    if report.filter == "none":
        return Params(status=status), errors

    start, end = read("from"), read("to")
    if start is None and end is None and report.default_days is not None:
        start, end = today - timedelta(days=report.default_days - 1), today
    if start and end and start > end:
        errors.append("The start date is after the end date; the two were swapped.")
        start, end = end, start
    if start and end and (end - start).days > MAX_RANGE_DAYS:
        errors.append(f"A range can span at most {MAX_RANGE_DAYS // 365} years; showing the most recent part.")
        start = end - timedelta(days=MAX_RANGE_DAYS)
    return Params(
        datetime.combine(start, datetime.min.time()) if start else None,
        datetime.combine(end + timedelta(days=1), datetime.min.time()) if end else None,
        None, status), errors


def _between(column, p):
    conds = []
    if p.start is not None:
        conds.append(column >= p.start)
    if p.end is not None:
        conds.append(column < p.end)
    return conds


def _cap(query):
    rows = query.limit(MAX_ROWS + 1).all()
    return rows[:MAX_ROWS], len(rows) > MAX_ROWS


def _f(value):
    return float(value) if value is not None else None


def _left(seconds):
    if seconds <= 0:
        return "Ended"
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    return f"{d}d {h}h" if d else f"{h}h {rem // 60}m" if h else f"{rem // 60}m"


def _method(payment_method, detail):
    if payment_method == "crypto":
        return "Cryptocurrency"
    return {"card": "Card", "upi": "UPI", "wallet": "Wallet"}.get(detail, "Not chosen" if not payment_method else "Online")


# ---- 1. daily auction report -----------------------------------------------------------------------
def daily_auctions(p):
    bids_by_auction = dict(db.session.query(Bid.auction_id, func.count(Bid.id))
                           .filter(*_between(Bid.bid_time, p)).group_by(Bid.auction_id).all())
    q = (db.session.query(Auction.id, Product.title, Seller.name, Category.name, Auction.status, Auction.start_time,
                          Auction.end_time, Auction.current_bid)
         .join(Product, Auction.product_id == Product.id).join(Seller, Seller.id == Product.seller_id)
         .join(Category, Category.id == Product.category_id)
         .filter(or_(and_(*_between(Auction.start_time, p)), and_(*_between(Auction.end_time, p)),
                     Auction.id.in_(list(bids_by_auction) or [-1])))
         .order_by(Auction.id))
    raw, truncated = _cap(q)
    rows, started, ended = [], 0, 0
    for aid, title, seller, cat, status, start, end, current in raw:
        s_today = p.start <= start < p.end
        e_today = status == "closed" and p.start <= end < p.end
        started, ended = started + s_today, ended + e_today
        rows.append((aid, title, seller, cat, AUCTION_STATUS.get(status, status), start, end, bids_by_auction.get(aid, 0),
                     _f(current), "Yes" if s_today else "No", "Yes" if e_today else "No"))
    revenue = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.payment_status == "successful", *_between(Payment.payment_date, p)).scalar()
    return Data(rows, [("Auctions with activity", len(rows), "int"), ("Started", started, "int"), ("Ended", ended, "int"),
                       ("Bids placed", sum(bids_by_auction.values()), "int"), ("Payments received", _f(revenue), "money")], truncated)


# ---- 2. active auctions -------------------------------------------------------------------------------
def active_auctions(p):
    bid_count = db.session.query(func.count(Bid.id)).filter(Bid.auction_id == Auction.id).correlate(Auction).scalar_subquery()
    q = (db.session.query(Auction.id, Product.title, Seller.name, Category.name, Auction.status, Auction.start_time, Auction.end_time,
                          bid_count, Auction.current_bid, Bidder.name)
         .join(Product, Auction.product_id == Product.id).join(Seller, Seller.id == Product.seller_id)
         .join(Category, Category.id == Product.category_id).outerjoin(Bidder, Bidder.id == Auction.highest_bidder_id)
         .filter(Auction.status.in_(("active", "scheduled"))).order_by(Auction.end_time, Auction.id))
    raw, truncated = _cap(q)
    now = utcnow()
    rows = [(aid, t, s, c, AUCTION_STATUS[st], start, end, _left((end - now).total_seconds()) if st == "active" else "Not started",
             n, _f(cur), top or "-") for aid, t, s, c, st, start, end, n, cur, top in raw]
    live = [r for r in raw if r[4] == "active"]
    return Data(rows, [("Live auctions", len(live), "int"), ("Scheduled", len(raw) - len(live), "int"),
                       ("Bids so far", sum(r[7] for r in raw), "int"), ("Current bids total", _f(sum((r[8] for r in live), Decimal(0))), "money")], truncated)


# ---- 3. completed auctions -----------------------------------------------------------------------------
def completed_auctions(p):
    bid_count = db.session.query(func.count(Bid.id)).filter(Bid.auction_id == Auction.id).correlate(Auction).scalar_subquery()
    q = (db.session.query(Auction.id, Product.title, Seller.name, Buyer.name, Winner.winning_amount, bid_count, Auction.start_time,
                          Auction.end_time, Payment.payment_status)
         .join(Product, Auction.product_id == Product.id).join(Seller, Seller.id == Product.seller_id)
         .outerjoin(Winner, Winner.auction_id == Auction.id).outerjoin(Buyer, Buyer.id == Winner.buyer_id)
         .outerjoin(Payment, Payment.auction_id == Auction.id)
         .filter(Auction.status == "closed", *_between(Auction.end_time, p)).order_by(Auction.end_time.desc(), Auction.id.desc()))
    raw, truncated = _cap(q)
    rows = [(aid, t, s, w or "No winner", _f(a), n, st, en, (pay or "n/a").capitalize()) for aid, t, s, w, a, n, st, en, pay in raw]
    won = [r for r in raw if r[3]]
    return Data(rows, [("Completed auctions", len(raw), "int"), ("With a winner", len(won), "int"), ("No bids", len(raw) - len(won), "int"),
                       ("Winning bids total", _f(sum((r[4] for r in won), Decimal(0))), "money"),
                       ("Paid so far", _f(sum((r[4] for r in won if r[8] == "successful"), Decimal(0))), "money")], truncated)


# ---- 4. highest selling products --------------------------------------------------------------------------
def top_products(p):
    q = (db.session.query(Product.title, Seller.name, Category.name, Buyer.name, Payment.amount, Payment.payment_date,
                          Payment.payment_method, Payment.method_detail)
         .join(Auction, Auction.product_id == Product.id).join(Payment, Payment.auction_id == Auction.id)
         .join(Seller, Seller.id == Product.seller_id).join(Buyer, Buyer.id == Payment.buyer_id)
         .join(Category, Category.id == Product.category_id)
         .filter(Payment.payment_status == "successful", *_between(Payment.payment_date, p))
         .order_by(Payment.amount.desc(), Product.title).limit(TOP_PRODUCTS))
    raw = q.all()
    rows = [(i + 1, t, s, c, b, _f(a), when, _method(pm, md)) for i, (t, s, c, b, a, when, pm, md) in enumerate(raw)]
    amounts = [r[4] for r in raw]
    return Data(rows, [("Products listed", len(raw), "int"), ("Total value", _f(sum(amounts, Decimal(0))), "money"),
                       ("Highest sale", _f(max(amounts)) if amounts else None, "money"),
                       ("Average sale", _f(sum(amounts, Decimal(0)) / len(amounts)) if amounts else None, "money")])


# ---- 5. highest bids ---------------------------------------------------------------------------------------------
def highest_bids(p):
    bid_count = db.session.query(func.count(Bid.id)).filter(Bid.auction_id == Auction.id).correlate(Auction).scalar_subquery()
    q = (db.session.query(Product.title, Seller.name, Category.name, Auction.status, Auction.current_bid, Product.starting_price,
                          bid_count, Bidder.name)
         .join(Auction, Auction.product_id == Product.id).join(Seller, Seller.id == Product.seller_id)
         .join(Category, Category.id == Product.category_id).join(Bidder, Bidder.id == Auction.highest_bidder_id)
         .filter(Auction.highest_bidder_id.isnot(None), Auction.status != "cancelled", *_between(Auction.start_time, p))
         .order_by(Auction.current_bid.desc(), Product.title))
    raw, truncated = _cap(q)
    rows = [(i + 1, t, s, c, AUCTION_STATUS.get(st, st), _f(cur), _f(start), _f((cur - start) / start * 100) if start else None, n, b)
            for i, (t, s, c, st, cur, start, n, b) in enumerate(raw)]
    curs = [r[4] for r in raw]
    return Data(rows, [("Auctions with bids", len(raw), "int"), ("Highest bid", _f(max(curs)) if curs else None, "money"),
                       ("Average highest bid", _f(sum(curs, Decimal(0)) / len(curs)) if curs else None, "money")], truncated)


# ---- 6. revenue ------------------------------------------------------------------------------------------------------
def revenue(p):
    q = (db.session.query(Payment.payment_date, Payment.amount, Payment.payment_method, CryptoPayment.amount)
         .outerjoin(CryptoPayment, CryptoPayment.payment_id == Payment.id)
         .filter(Payment.payment_status == "successful", *_between(Payment.payment_date, p)).order_by(Payment.payment_date))
    raw, truncated = _cap(q)
    days = {}
    for when, amount, method, eth in raw:
        d = days.setdefault(when.date(), [0, Decimal(0), Decimal(0), Decimal(0)])
        d[0] += 1
        d[2 if method == "crypto" else 1] += amount
        if method == "crypto":
            d[3] += eth or 0
    rows = [(day, n, _f(sim), _f(cry), _f(sim + cry), _f(eth)) for day, (n, sim, cry, eth) in sorted(days.items())]
    total = sum((r[4] for r in rows), 0.0)
    return Data(rows, [("Days with revenue", len(rows), "int"), ("Paid sales", sum(r[1] for r in rows), "int"), ("Total revenue", total, "money"),
                       ("Via crypto", sum((r[3] for r in rows), 0.0), "money"), ("ETH received", sum((r[5] for r in rows), 0.0), "eth")], truncated)


# ---- 7. user activity ----------------------------------------------------------------------------------------------------
def user_activity(p):
    def count_by(column, *filters):
        return dict(db.session.query(column, func.count()).filter(*filters).group_by(column).all())

    bids = count_by(Bid.buyer_id, *_between(Bid.bid_time, p))
    won = count_by(Winner.buyer_id, *_between(Winner.winning_time, p))
    listed = count_by(Product.seller_id, *_between(Product.created_at, p))
    purchases = count_by(Payment.buyer_id, Payment.payment_status == "successful", *_between(Payment.payment_date, p))
    reviews = count_by(Review.buyer_id, *_between(Review.created_at, p))
    users = db.session.query(User.id, User.name, User.email, User.role, User.created_at).all()
    rows = []
    for uid, name, email, role, joined in users:
        counts = (bids.get(uid, 0), won.get(uid, 0), listed.get(uid, 0), purchases.get(uid, 0), reviews.get(uid, 0))
        if any(counts):
            rows.append((name, email, role.capitalize(), joined, *counts, sum(counts)))
    rows.sort(key=lambda r: (-r[9], r[0].lower()))
    rows, truncated = rows[:MAX_ROWS], len(rows) > MAX_ROWS
    return Data(rows, [("Active users", len(rows), "int"), ("Bids placed", sum(r[4] for r in rows), "int"),
                       ("Products listed", sum(r[6] for r in rows), "int"), ("Paid purchases", sum(r[7] for r in rows), "int")], truncated)


# ---- 8. seller performance ------------------------------------------------------------------------------------------------
def seller_performance(p):
    listings = dict(db.session.query(Product.seller_id, func.count(Product.id)).filter(*_between(Product.created_at, p))
                    .group_by(Product.seller_id).all())
    # everything below is about auctions that ENDED in the period, so the ratios stay between 0 and 100%
    ended = (db.session.query(Product.seller_id, func.count(Auction.id), func.count(Winner.id),
                              func.coalesce(func.sum(case((Payment.payment_status == "successful", 1), else_=0)), 0),
                              func.coalesce(func.sum(case((Payment.payment_status == "successful", Payment.amount), else_=0)), 0))
             .join(Auction, Auction.product_id == Product.id).outerjoin(Winner, Winner.auction_id == Auction.id)
             .outerjoin(Payment, Payment.auction_id == Auction.id)
             .filter(Auction.status == "closed", *_between(Auction.end_time, p)).group_by(Product.seller_id).all())
    ended = {sid: (done, with_winner, int(paid), Decimal(rev)) for sid, done, with_winner, paid, rev in ended}
    ratings = {sid: (float(avg), n) for sid, avg, n in db.session.query(Product.seller_id, func.avg(Review.rating), func.count(Review.id))
               .join(Review, Review.product_id == Product.id).filter(Review.is_hidden.is_(False)).group_by(Product.seller_id).all()}
    rows = []
    for sid, name, email in db.session.query(User.id, User.name, User.email).filter(User.role == "seller").all():
        done, with_winner, paid, rev = ended.get(sid, (0, 0, 0, Decimal(0)))
        avg_rating, n_reviews = ratings.get(sid, (None, 0))
        rows.append((name, email, listings.get(sid, 0), done, with_winner, paid, _f(rev),
                     round(100 * paid / done, 1) if done else None, _f(rev / paid) if paid else None,
                     round(avg_rating, 1) if avg_rating is not None else None, n_reviews))
    rows.sort(key=lambda r: (-(r[6] or 0), r[0].lower()))
    return Data(rows, [("Sellers", len(rows), "int"), ("Auctions completed", sum(r[3] for r in rows), "int"),
                       ("Paid sales", sum(r[5] for r in rows), "int"), ("Revenue", sum((r[6] or 0 for r in rows), 0.0), "money")])


# ---- 9. product ratings -----------------------------------------------------------------------------------------------------
def product_ratings(p):
    def stars(n):
        return func.sum(case((Review.rating == n, 1), else_=0))

    visible = (db.session.query(Product.id, Product.title, Seller.name, Category.name, func.avg(Review.rating), func.count(Review.id),
                                stars(5), stars(4), stars(3), stars(2), stars(1), func.max(Review.created_at))
               .join(Review, Review.product_id == Product.id).join(Seller, Seller.id == Product.seller_id)
               .join(Category, Category.id == Product.category_id)
               .filter(Review.is_hidden.is_(False), *_between(Review.created_at, p))
               .group_by(Product.id, Product.title, Seller.name, Category.name)
               .order_by(func.avg(Review.rating).desc(), func.count(Review.id).desc(), Product.title))
    raw, truncated = _cap(visible)
    hidden = dict(db.session.query(Review.product_id, func.count(Review.id)).filter(Review.is_hidden.is_(True), *_between(Review.created_at, p))
                  .group_by(Review.product_id).all())
    rows = [(t, s, c, round(float(avg), 1), n, int(f5), int(f4), int(f3), int(f2), int(f1), hidden.get(pid, 0), last)
            for pid, t, s, c, avg, n, f5, f4, f3, f2, f1, last in raw]
    total = sum(r[4] for r in rows)
    stars_sum = sum(5 * r[5] + 4 * r[6] + 3 * r[7] + 2 * r[8] + r[9] for r in rows)  # exact: from the star counts
    mean = stars_sum / total if total else None
    return Data(rows, [("Products reviewed", len(rows), "int"), ("Visible reviews", total, "int"),
                       ("Average rating", round(mean, 2) if mean is not None else None, "rating"), ("Hidden by moderators", sum(r[10] for r in rows), "int")], truncated)


# ---- 10. payments --------------------------------------------------------------------------------------------------------------
def payments(p):
    q = (db.session.query(Payment.id, Auction.id, Product.title, Buyer.name, Seller.name, Payment.amount, Payment.payment_method,
                          Payment.method_detail, Payment.payment_status, Payment.attempts, Payment.created_at, Payment.payment_date, Invoice.number)
         .join(Auction, Auction.id == Payment.auction_id).join(Product, Product.id == Auction.product_id)
         .join(Buyer, Buyer.id == Payment.buyer_id).join(Seller, Seller.id == Product.seller_id)
         .outerjoin(Invoice, Invoice.payment_id == Payment.id).filter(*_between(Payment.created_at, p))
         .order_by(Payment.created_at.desc(), Payment.id.desc()))
    if p.status != "all":
        q = q.filter(Payment.payment_status == p.status)
    raw, truncated = _cap(q)
    rows = [(pid, aid, t, b, s, _f(a), _method(pm, md), st.capitalize(), n, created, paid, inv or "-")
            for pid, aid, t, b, s, a, pm, md, st, n, created, paid, inv in raw]

    def total(status):
        return sum((r[5] for r in rows if r[7].lower() == status), 0.0)

    return Data(rows, [("Payments", len(rows), "int"), ("Successful", sum(r[7] == "Successful" for r in rows), "int"),
                       ("Pending", sum(r[7] == "Pending" for r in rows), "int"), ("Failed", sum(r[7] == "Failed" for r in rows), "int"),
                       ("Collected", total("successful"), "money"), ("Outstanding", total("pending") + total("failed"), "money")], truncated)


# ---- 11. cryptocurrency transactions ------------------------------------------------------------------------------------------------
def crypto_transactions(p):
    q = (db.session.query(Payment.id, Auction.id, Product.title, Buyer.name, CryptoPayment.amount, Payment.amount, CryptoPayment.exchange_rate,
                          CryptoPayment.blockchain_network, CryptoPayment.status, CryptoPayment.confirmations, CryptoPayment.block_number,
                          CryptoPayment.transaction_date, CryptoPayment.transaction_hash, CryptoPayment.wallet_address,
                          CryptoPayment.seller_address, CryptoPayment.failure_reason)
         .join(Payment, Payment.id == CryptoPayment.payment_id).join(Auction, Auction.id == Payment.auction_id)
         .join(Product, Product.id == Auction.product_id).join(Buyer, Buyer.id == Payment.buyer_id)
         .filter(CryptoPayment.transaction_hash.isnot(None), *_between(CryptoPayment.transaction_date, p))
         .order_by(CryptoPayment.transaction_date.desc(), CryptoPayment.id.desc()))
    raw, truncated = _cap(q)
    rows = [(pid, aid, t, b, _f(eth), _f(inr), _f(rate), net, st.capitalize(), conf, block, when, h, w, sw, reason or "")
            for pid, aid, t, b, eth, inr, rate, net, st, conf, block, when, h, w, sw, reason in raw]
    ok = [r for r in rows if r[8] == "Confirmed"]
    return Data(rows, [("Transactions", len(rows), "int"), ("Confirmed", len(ok), "int"),
                       ("Failed", sum(r[8] == "Failed" for r in rows), "int"), ("Pending", sum(r[8] == "Pending" for r in rows), "int"),
                       ("ETH confirmed", sum((r[4] for r in ok), 0.0), "eth"), ("Value confirmed", sum((r[5] for r in ok), 0.0), "money")], truncated)


C = Column
REPORTS = {r.key: r for r in (
    Report("daily-auctions", "Daily Auction Report", "Every auction that started, ended or received bids on the chosen day.",
           (C("id", "Auction", "int", .5), C("product", "Product", weight=1.6), C("seller", "Seller"), C("category", "Category"), C("status", "Status", weight=.8),
            C("start", "Starts (UTC)", "datetime", 1.1), C("end", "Ends (UTC)", "datetime", 1.1), C("bids", "Bids that day", "int", .7),
            C("current", "Current bid", "money", .9), C("started", "Started", weight=.6), C("ended", "Ended", weight=.6)),
           daily_auctions, filter="day"),
    Report("active-auctions", "Active Auction Report", "All live and upcoming auctions right now.",
           (C("id", "Auction", "int", .5), C("product", "Product", weight=1.6), C("seller", "Seller"), C("category", "Category"), C("status", "Status", weight=.8),
            C("start", "Starts (UTC)", "datetime", 1.1), C("end", "Ends (UTC)", "datetime", 1.1), C("left", "Time left", weight=.8),
            C("bids", "Bids", "int", .5), C("current", "Current bid", "money", .9), C("top", "Top bidder")),
           active_auctions, filter="none"),
    Report("completed-auctions", "Completed Auction Report", "Auctions that ended in the period, with winner and payment status.",
           (C("id", "Auction", "int", .5), C("product", "Product", weight=1.6), C("seller", "Seller"), C("winner", "Winner"), C("amount", "Winning bid", "money", .9),
            C("bids", "Bids", "int", .5), C("start", "Started (UTC)", "datetime", 1.1), C("end", "Ended (UTC)", "datetime", 1.1), C("payment", "Payment", weight=.8)),
           completed_auctions, filter_label="Auction end date"),
    Report("top-products", "Highest Selling Products", f"The {TOP_PRODUCTS} highest-value paid sales in the period.",
           (C("rank", "#", "int", .3), C("product", "Product", weight=1.6), C("seller", "Seller"), C("category", "Category"), C("buyer", "Buyer"),
            C("amount", "Sale value", "money", .9), C("paid", "Paid on (UTC)", "datetime", 1.1), C("method", "Method", weight=.9)),
           top_products, filter_label="Payment date"),
    Report("highest-bids", "Highest Bid Report", "Auctions ranked by their highest bid, with the increase over the starting price.",
           (C("rank", "#", "int", .3), C("product", "Product", weight=1.6), C("seller", "Seller"), C("category", "Category"), C("status", "Status", weight=.8),
            C("bid", "Highest bid", "money", .9), C("start", "Starting price", "money", .9), C("inc", "Increase", "pct", .7), C("bids", "Bids", "int", .5),
            C("bidder", "Highest bidder")),
           highest_bids, filter_label="Auction start date"),
    Report("revenue", "Revenue Report", "Successful payments per day, split into simulated and cryptocurrency.",
           (C("day", "Date", "date", .9), C("n", "Paid sales", "int", .7), C("sim", "Simulated payments", "money", 1.1), C("cry", "Cryptocurrency", "money", 1.1),
            C("total", "Total revenue", "money", 1.1), C("eth", "ETH received", "eth", 1)),
           revenue, filter_label="Payment date"),
    Report("user-activity", "User Activity Report", "What each user did in the period (users with no activity are left out).",
           (C("name", "User", weight=1.2), C("email", "Email", weight=1.6), C("role", "Role", weight=.7), C("joined", "Joined (UTC)", "datetime", 1.1),
            C("bids", "Bids", "int", .5), C("won", "Auctions won", "int", .7), C("listed", "Products listed", "int", .8), C("buys", "Paid purchases", "int", .8),
            C("reviews", "Reviews", "int", .6), C("total", "Total actions", "int", .7)),
           user_activity, filter_label="Activity date"),
    Report("seller-performance", "Seller Performance Report", "How each seller did on auctions that ended in the period. Ratings are all-time.",
           (C("name", "Seller", weight=1.2), C("email", "Email", weight=1.6), C("listed", "Listings created", "int", .8), C("done", "Auctions completed", "int", .9),
            C("winner", "With a winner", "int", .8), C("paid", "Paid sales", "int", .7), C("rev", "Revenue", "money", 1), C("rate", "Sell-through %", "pct", .8),
            C("avg", "Average sale", "money", .9), C("rating", "Avg rating", "rating", .7), C("reviews", "Reviews", "int", .6)),
           seller_performance, filter_label="Auction end date (listings: creation date)"),
    Report("product-ratings", "Product Rating Report", "Average rating and star breakdown per product (hidden reviews are excluded).",
           (C("product", "Product", weight=1.6), C("seller", "Seller"), C("category", "Category"), C("avg", "Average", "rating", .7), C("n", "Reviews", "int", .6),
            C("s5", "5 stars", "int", .5), C("s4", "4 stars", "int", .5), C("s3", "3 stars", "int", .5), C("s2", "2 stars", "int", .5), C("s1", "1 star", "int", .5),
            C("hidden", "Hidden", "int", .5), C("last", "Latest review (UTC)", "datetime", 1.1)),
           product_ratings, filter_label="Review date", default_days=None),
    Report("payments", "Payment Report", "Every payment, whatever its status, with the invoice number once paid.",
           (C("id", "Payment", "int", .5), C("auction", "Auction", "int", .5), C("product", "Product", weight=1.5), C("buyer", "Buyer"), C("seller", "Seller"),
            C("amount", "Amount", "money", .9), C("method", "Method", weight=.9), C("status", "Status", weight=.8), C("attempts", "Tries", "int", .4),
            C("created", "Created (UTC)", "datetime", 1.1), C("paid", "Paid (UTC)", "datetime", 1.1), C("invoice", "Invoice", "mono", 1.1)),
           payments, filter_label="Payment created date", statuses=True),
    Report("crypto-transactions", "Cryptocurrency Transaction Report", "Submitted blockchain payments with their on-chain details (test network).",
           (C("id", "Payment", "int", .5), C("auction", "Auction", "int", .5), C("product", "Product", weight=1.2), C("buyer", "Buyer"), C("eth", "ETH", "eth", .8),
            C("inr", "INR value", "money", .9), C("rate", "INR per ETH", "money", .9), C("net", "Network", weight=.9), C("status", "Status", weight=.8),
            C("conf", "Conf.", "int", .4), C("block", "Block", "int", .6), C("when", "Submitted (UTC)", "datetime", 1.1), C("hash", "Transaction hash", "mono", 2.4),
            C("wallet", "Buyer wallet", "mono", 1.6), C("seller_wallet", "Seller wallet", "mono", 1.6), C("reason", "Failure reason", weight=1.3)),
           crypto_transactions, filter_label="Transaction date", pdf_skip=("wallet", "seller_wallet", "rate")),
)}


def run(report, params):
    return report.fetch(params)
