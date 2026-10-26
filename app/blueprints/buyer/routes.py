from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from ...extensions import db
from ...models import Auction, Bid, MaxBid, Product, Watchlist, Winner
from ...services import blockchain_service, buyer_cards_service
from ...services import review_service as rs
from ...services.catalog import PUBLIC_STATUSES, bid_counts, visible_auction_or_404
from ...utils import role_required, safe_redirect_target
from . import bp

PER_PAGE = 15


@bp.route("/")
@role_required("member")
def dashboard():
    uid = current_user.id
    bidding_on = (db.session.query(func.count(func.distinct(Bid.auction_id)))
                  .join(Auction, Bid.auction_id == Auction.id)
                  .filter(Bid.buyer_id == uid, Auction.status.in_(("scheduled", "active"))).scalar())
    leading = Auction.query.filter_by(highest_bidder_id=uid, status="active").count()
    stats = {
        "bidding_on": bidding_on,
        "leading": leading,
        "watching": Watchlist.query.filter_by(user_id=uid).count(),
        "won": Winner.query.filter_by(buyer_id=uid).count(),
    }
    return render_template("buyer/dashboard.html", stats=stats)


@bp.route("/bids")
@role_required("member")
def bids():
    page = (Bid.query.filter_by(buyer_id=current_user.id)
            .order_by(Bid.bid_time.desc(), Bid.id.desc())
            .paginate(page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False))
    ids = {b.auction_id for b in page.items}
    maxes = {m.auction_id: m.max_amount for m in MaxBid.query.filter(MaxBid.buyer_id == current_user.id, MaxBid.auction_id.in_(ids))} if ids else {}
    return render_template("buyer/bids.html", page=page, maxes=maxes)


@bp.route("/watchlist")
@role_required("member")
def watchlist():
    auctions = (Auction.query.join(Product)
                .join(Watchlist, Watchlist.product_id == Product.id)
                .filter(Watchlist.user_id == current_user.id,
                        Product.approval_status == "approved", Auction.status.in_(PUBLIC_STATUSES))
                .order_by(Auction.end_time.asc()).all())
    return render_template("buyer/watchlist.html", auctions=auctions,
                           counts=bid_counts([a.id for a in auctions]),
                           ratings=rs.stats_for_products([a.product_id for a in auctions]))


@bp.route("/watchlist/<int:auction_id>/toggle", methods=["POST"])
@role_required("member")
def toggle_watch(auction_id):
    auction = visible_auction_or_404(auction_id)
    if auction.product.seller_id == current_user.id:
        abort(403)  # watching your own listing means nothing: you get its notices as the seller anyway
    entry = Watchlist.query.filter_by(user_id=current_user.id, product_id=auction.product_id).first()
    if entry:
        db.session.delete(entry)
        flash("Removed from your watchlist.", "info")
    else:
        db.session.add(Watchlist(user_id=current_user.id, product_id=auction.product_id))
        flash("Added to your watchlist.", "success")
    db.session.commit()
    back = request.referrer
    return redirect(safe_redirect_target(back) or url_for("auctions.detail", auction_id=auction.id))


@bp.route("/won")
@role_required("member")
def won():
    wins = (Winner.query.filter_by(buyer_id=current_user.id)
            .order_by(Winner.winning_time.desc()).all())
    return render_template("buyer/won.html", wins=wins)


@bp.route("/cards")
@role_required("member")
def cards():
    """My cards: what the buyer owns on the blockchain and what is still being paid for."""
    rows = buyer_cards_service.buyer_cards(current_user)
    return render_template("buyer/cards.html", rows=rows, tx_url=blockchain_service.explorer_url,
                           owned=sum(1 for r in rows if r["code"] == "OWNED"))
