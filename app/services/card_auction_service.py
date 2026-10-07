"""Create an auction for a platform-verified, token-backed card: the only seller path from card to auction.

Everything is decided here on the server. Under a lock, the listing gate (auction_validation_service) is run
against fresh state and the Auction row is inserted in the same transaction, so two requests cannot both pass
the duplicate check. The database's unique constraint on auctions.product_id backs this up for the same card.
The lock is per process: with several server processes, two different records of the same graded card could
in theory race, which is why that case is also flagged to the admin as a potential duplicate.
"""
import threading
from datetime import timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Auction, utcnow
from . import auction_service
from .auction_validation_service import ListingBlocked, assert_listable
from .notifications import notify

MIN_STARTING_BID = Decimal("1.00")
MAX_STARTING_BID = Decimal("10000000")
START_GRACE = timedelta(minutes=5)  # "start now" must survive the round trip of a form

_lock = threading.RLock()


class CardAuctionError(Exception):
    def __init__(self, message, status=400, violations=()):
        super().__init__(message)
        self.message = message
        self.status = status
        self.violations = list(violations)


def _starting_bid(raw):
    try:
        amount = auction_service.parse_amount(raw)  # ASCII digits, at most 2 decimals, no NaN/Infinity/exponent
    except auction_service.BidError as e:
        raise CardAuctionError(e.message)
    if not MIN_STARTING_BID <= amount <= MAX_STARTING_BID:
        raise CardAuctionError(f"The starting bid must be between {MIN_STARTING_BID:,} and {MAX_STARTING_BID:,}.")
    return amount


def _window(start_time, duration_hours, now):
    cfg = current_app.config
    if isinstance(duration_hours, bool) or not isinstance(duration_hours, int):
        raise CardAuctionError("Choose how long the auction runs.")
    duration = timedelta(hours=duration_hours)
    if duration < timedelta(minutes=cfg["MIN_AUCTION_MINUTES"]):
        raise CardAuctionError(f"An auction must run for at least {cfg['MIN_AUCTION_MINUTES']} minutes.")
    if duration > timedelta(days=cfg["MAX_AUCTION_DAYS"]):
        raise CardAuctionError(f"An auction cannot run longer than {cfg['MAX_AUCTION_DAYS']} days.")

    start = start_time or now
    if start < now - START_GRACE:
        raise CardAuctionError("The start time cannot be in the past.")
    if start > now + timedelta(days=cfg["MAX_AUCTION_DAYS"]):
        raise CardAuctionError(f"The auction cannot start more than {cfg['MAX_AUCTION_DAYS']} days from now.")
    start = max(start, now)
    return start, start + duration


def create_card_auction(product, seller, starting_bid, start_time, duration_hours, now=None):
    """Validate everything, run the listing gate and create the auction. Raises CardAuctionError."""
    now = now or utcnow()
    if product.seller_id != seller.id:
        raise CardAuctionError("This card does not belong to you.", 403)
    if product.collectible_card is None:
        raise CardAuctionError("Only trading cards are listed this way.")
    amount = _starting_bid(starting_bid)
    start, end = _window(start_time, duration_hours, now)

    with _lock:
        db.session.refresh(product)  # decide on fresh state, not on whatever this session loaded earlier
        if product.approval_status != "approved":
            raise CardAuctionError("This listing has not been approved for auction.", 409)
        try:
            assert_listable(product)
        except ListingBlocked as e:
            raise CardAuctionError("This card cannot be listed: " + " ".join(i.message for i in e.check.violations),
                                   409, e.check.violations)

        product.starting_price = amount
        product.auction_start, product.auction_end = start, end
        db.session.add(Auction(
            product_id=product.id, start_time=start, end_time=end, original_end_time=end,
            current_bid=amount,  # the first bid must be at least the starting bid
            status="active" if start <= now else "scheduled"))
        notify(seller.id, "Auction created", f'Your auction for "{product.title}" has been created.',
               url=f"/seller/products/{product.id}")
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise CardAuctionError("This card already has an auction.", 409)
    return product.auction
