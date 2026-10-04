"""Public catalog queries shared by the browse, detail and buyer pages."""
from decimal import Decimal, InvalidOperation

from flask import abort
from sqlalchemy import func, select

from ..extensions import db
from ..models import Auction, Bid, Category, Product
from ..utils import like_pattern

PUBLIC_STATUSES = ("scheduled", "active", "closed")  # cancelled listings are hidden
STATUS_FILTERS = {"active": ("active",), "upcoming": ("scheduled",), "ended": ("closed",), "all": PUBLIC_STATUSES}
SORTS = ("ending", "newest", "price_low", "price_high", "most_bids")
MAX_TERMS = 6
MAX_PRICE = Decimal("9999999999")


def visible_auctions():
    """Auctions of approved products that are not cancelled."""
    return (Auction.query.join(Product)
            .filter(Product.approval_status == "approved", Auction.status.in_(PUBLIC_STATUSES)))


def visible_auction_or_404(auction_id):
    auction = visible_auctions().filter(Auction.id == auction_id).first()
    if auction is None:
        abort(404)
    return auction


def _price(raw):
    try:
        value = Decimal((raw or "").strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() and 0 <= value <= MAX_PRICE else None


def parse_filters(args):
    """Normalise query-string filters; anything invalid falls back to a safe default."""
    status = args.get("status", "active")
    sort = args.get("sort", "ending")
    return {
        "q": args.get("q", "").strip()[:100],
        "category": args.get("category", type=int),
        "status": status if status in STATUS_FILTERS else "active",
        "sort": sort if sort in SORTS else "ending",
        "min_price": _price(args.get("min_price")),
        "max_price": _price(args.get("max_price")),
    }


def search_auctions(f):
    """Apply parsed filters. Each search word must appear in the title, description or category."""
    query = visible_auctions().join(Category, Product.category_id == Category.id)
    query = query.filter(Auction.status.in_(STATUS_FILTERS[f["status"]]))

    for term in f["q"].split()[:MAX_TERMS]:
        like = like_pattern(term)
        query = query.filter(
            Product.title.ilike(like, escape="\\")
            | Product.description.ilike(like, escape="\\")
            | Category.name.ilike(like, escape="\\"))
    if f["category"]:
        query = query.filter(Product.category_id == f["category"])
    # price filters apply to the current bid (the starting price while there are no bids)
    if f["min_price"] is not None:
        query = query.filter(Auction.current_bid >= f["min_price"])
    if f["max_price"] is not None:
        query = query.filter(Auction.current_bid <= f["max_price"])

    bid_count = select(func.count(Bid.id)).where(Bid.auction_id == Auction.id).scalar_subquery()
    order = {
        "ending": (Auction.end_time.asc(),),
        "newest": (Auction.start_time.desc(), Auction.id.desc()),
        "price_low": (Auction.current_bid.asc(),),
        "price_high": (Auction.current_bid.desc(),),
        "most_bids": (bid_count.desc(), Auction.end_time.asc()),
    }[f["sort"]]
    return query.order_by(*order, Auction.id.asc())


def bid_counts(auction_ids):
    if not auction_ids:
        return {}
    rows = (db.session.query(Bid.auction_id, func.count(Bid.id))
            .filter(Bid.auction_id.in_(auction_ids)).group_by(Bid.auction_id).all())
    return dict(rows)
