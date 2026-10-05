from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ... import sockets
from ...models import Auction, Category, Product, Watchlist, utcnow
from ...ratelimit import limited
from ...services import auction_service
from ...services import review_service as rs
from ...services.auction_service import BidError
from ...services.catalog import (
    SORTS, STATUS_FILTERS, bid_counts, parse_filters, search_auctions, visible_auction_or_404,
)
from . import bp

PER_PAGE = 12


def _refresh():
    """Start/close anything due, so pages are right even if the background loop is behind."""
    for info in auction_service.run_maintenance():
        sockets.emit_closed(info)


@bp.route("/")
def browse():
    _refresh()
    f = parse_filters(request.args)
    page = search_auctions(f).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    return render_template(
        "auctions/browse.html", page=page, f=f, counts=bid_counts([a.id for a in page.items]),
        ratings=rs.stats_for_products([a.product_id for a in page.items]),
        categories=Category.query.order_by(Category.name).all(),
        statuses=list(STATUS_FILTERS), sorts=SORTS,
        # query-string for pagination links: current filters minus empty values
        qs={k: v for k, v in {
            "q": f["q"], "category": f["category"], "status": f["status"], "sort": f["sort"],
            "min_price": request.args.get("min_price") if f["min_price"] is not None else None,
            "max_price": request.args.get("max_price") if f["max_price"] is not None else None,
        }.items() if v not in (None, "")},
    )


@bp.route("/<int:auction_id>")
def detail(auction_id):
    _refresh()
    auction = visible_auction_or_404(auction_id)
    bids = auction.bids[:20]  # already ordered by amount, highest first
    watching = False
    if current_user.is_authenticated and current_user.role == "buyer":
        watching = Watchlist.query.filter_by(
            user_id=current_user.id, product_id=auction.product_id).first() is not None
    pid = auction.product_id
    eligible = rs.can_review(current_user, auction.id)

    # Similar items: other active auctions in the same category
    similar = (Auction.query.join(Product)
              .filter(Product.category_id == auction.product.category_id,
                      Auction.status.in_(("scheduled", "active")),
                      Auction.id != auction.id)
              .order_by(Auction.end_time.asc())
              .limit(6).all())

    return render_template("auctions/detail.html", auction=auction, product=auction.product,
                           bids=bids, bid_total=len(auction.bids), watching=watching,
                           reviews=rs.visible_reviews(pid), stats=rs.stats_for_products([pid]).get(pid),
                           seller_rating=rs.seller_stats(auction.product.seller_id),
                           can_review=eligible, mine=rs.own_review(current_user, pid) if eligible else None,
                           state=auction_service.auction_state(auction),
                           can_bid=current_user.is_authenticated and current_user.role == "buyer",
                           similar=similar, similar_counts=bid_counts([a.id for a in similar]),
                           similar_stats=rs.stats_for_products([a.product_id for a in similar]))


@bp.route("/<int:auction_id>/state")
def state(auction_id):
    _refresh()
    auction = visible_auction_or_404(auction_id)
    return jsonify(auction_service.auction_state(auction))


@bp.route("/<int:auction_id>/bid", methods=["POST"])
@login_required
@limited("bid", 30, 60, by="user")
def place_bid(auction_id):
    wants_json = request.headers.get("Accept", "").startswith("application/json")
    try:
        result = auction_service.place_bid(auction_id, current_user, request.form.get("amount"))
    except BidError as e:
        if wants_json:
            return jsonify(ok=False, error=e.message), e.status
        flash(e.message, "danger")
        return redirect(url_for("auctions.detail", auction_id=auction_id))

    auction = visible_auction_or_404(auction_id)
    payload = sockets.emit_bid(result, auction)  # tell everyone watching this auction
    if wants_json:
        return jsonify(ok=True, **payload)
    flash("Your bid was placed." + (" The auction was extended by 2 minutes." if result.extended else ""), "success")
    return redirect(url_for("auctions.detail", auction_id=auction_id))
