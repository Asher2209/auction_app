"""Auction engine: bid validation, anti-sniping, activation and closing.

Concurrency model
-----------------
* Every state change is a compare-and-set UPDATE whose WHERE clause repeats the values the
  decision was based on (status, end time, current bid, highest bidder). If another bid or
  the closer got in first, no row matches and the attempt is re-validated against fresh state.
  This is what keeps two simultaneous bids from both "winning", on SQLite and on MySQL.
* A process-wide lock additionally serialises bids and closing inside one server process,
  which avoids SQLite "database is locked" errors under threads.
"""
import re
import threading
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import and_, update

from ..extensions import db
from ..models import Auction, Bid, Payment, Watchlist, Winner, utcnow
from . import payment_service
from .notifications import notify

_lock = threading.RLock()
_AMOUNT_RE = re.compile(r"^[0-9]{1,10}(\.[0-9]{1,2})?$")  # ASCII digits only; no signs, NaN/Infinity, exponents
MAX_ATTEMPTS = 3


class BidError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class BidResult:
    auction_id: int
    bid: Bid
    previous_bidder_id: int | None
    extended: bool


def _money(value):
    return f"{current_app.config['CURRENCY_SYMBOL']}{value:,.2f}"


def iso(dt):
    """UTC timestamps go to the browser as ISO-8601 with a Z suffix."""
    return dt.isoformat() + "Z"


def parse_amount(raw):
    text = str(raw if raw is not None else "").strip()
    if not _AMOUNT_RE.match(text):
        raise BidError("Enter a valid amount with at most 2 decimal places.")
    amount = Decimal(text)
    if amount <= 0:
        raise BidError("Enter an amount greater than zero.")
    return amount


def min_next_bid(auction):
    """First bid may equal the starting price; every later bid must beat the current one."""
    if auction.highest_bidder_id is None:
        return auction.current_bid
    return auction.current_bid + current_app.config["MIN_BID_INCREMENT"]


def bid_count(auction_id):
    return Bid.query.filter_by(auction_id=auction_id).count()


def auction_state(auction, now=None):
    """JSON-safe snapshot used by the state endpoint and the live-update events."""
    now = now or utcnow()
    winner = auction.winner if auction.status == "closed" else None
    return {
        "winner_mask": (winner.buyer.name[:1] + "***") if winner else None,
        "winning_amount": f"{winner.winning_amount:.2f}" if winner else None,
        "auction_id": auction.id,
        "status": auction.status,
        "current_bid": f"{auction.current_bid:.2f}",
        "min_next_bid": f"{min_next_bid(auction):.2f}",
        "bid_count": bid_count(auction.id),
        "leading_bidder_id": auction.highest_bidder_id,
        "start_time": iso(auction.start_time),
        "end_time": iso(auction.end_time),
        "extension_count": auction.extension_count,
        "server_now": iso(now),
    }


# ---- placing bids ----------------------------------------------------------
def _check_open(auction, user, now):
    if auction is None or auction.product.approval_status != "approved":
        raise BidError("Auction not found.", 404)
    if auction.product.seller_id == user.id:
        raise BidError("You cannot bid on your own product.", 403)
    if auction.status == "scheduled":
        raise BidError("This auction has not started yet.")
    if auction.status == "cancelled":
        raise BidError("This auction was cancelled.")
    if auction.status != "active" or now >= auction.end_time:
        raise BidError("This auction has ended.")


def place_bid(auction_id, user, raw_amount, now=None):
    """Validate and record a bid. Raises BidError with a user-safe message on any rule failure."""
    now = now or utcnow()
    amount = parse_amount(raw_amount)
    if user.role != "buyer":
        raise BidError("Only buyer accounts can place bids.", 403)

    cfg = current_app.config
    with _lock:
        activate_due(now)  # a bid right after the start time must not be refused as "not started"
        for _ in range(MAX_ATTEMPTS):
            auction = db.session.get(Auction, auction_id, populate_existing=True)
            _check_open(auction, user, now)

            needed = min_next_bid(auction)
            if amount < needed:
                label = "at least the starting price" if auction.highest_bidder_id is None else "higher than the current bid"
                raise BidError(f"Your bid must be {label}: minimum {_money(needed)}.")

            previous_bidder = auction.highest_bidder_id
            extended = (auction.end_time - now) <= timedelta(seconds=cfg["SNIPE_WINDOW_SECONDS"])
            new_end = auction.end_time + timedelta(seconds=cfg["SNIPE_EXTENSION_SECONDS"]) if extended else auction.end_time

            same_bidder = (Auction.highest_bidder_id.is_(None) if previous_bidder is None
                           else Auction.highest_bidder_id == previous_bidder)
            values = {"current_bid": amount, "highest_bidder_id": user.id, "end_time": new_end}
            if extended:
                values["extension_count"] = Auction.extension_count + 1
            claimed = db.session.execute(
                update(Auction)
                .where(and_(Auction.id == auction.id, Auction.status == "active",
                            Auction.end_time == auction.end_time, Auction.current_bid == auction.current_bid,
                            same_bidder))
                .values(**values),
                execution_options={"synchronize_session": False},
            ).rowcount
            if claimed != 1:  # someone else changed the auction first: re-check against fresh state
                db.session.rollback()
                continue

            bid = Bid(auction_id=auction.id, buyer_id=user.id, amount=amount, bid_time=now)
            db.session.add(bid)
            title = auction.product.title
            page = f"/auctions/{auction.id}"
            seller_page = f"/seller/products/{auction.product_id}"
            notify(user.id, "Bid accepted", f'Your bid of {_money(amount)} on "{title}" is the highest bid.', url=page)
            if previous_bidder and previous_bidder != user.id:
                notify(previous_bidder, "You have been outbid",
                       f'Someone placed a higher bid ({_money(amount)}) on "{title}".', url=page, email=True)
            notify(auction.product.seller_id, "New bid received", f'New bid of {_money(amount)} on "{title}".', url=seller_page)

            # Notify watchers of this auction that a new bid was placed
            from ..models import Watchlist
            watchers = db.session.query(Watchlist.user_id).filter_by(product_id=auction.product_id).all()
            for (watcher_id,) in watchers:
                if watcher_id != user.id:  # don't notify the bidder themselves
                    notify(watcher_id, "New bid on watched item",
                           f'Someone bid {_money(amount)} on "{title}", now the highest bid.', url=page, email=True)
            db.session.commit()
            db.session.refresh(auction)
            return BidResult(auction.id, bid, previous_bidder, extended)

    raise BidError("Another bid was placed at the same moment. Please try again.", 409)


# ---- lifecycle: start and close ---------------------------------------------
def activate_due(now=None):
    """scheduled -> active once the start time has passed. Returns the number started."""
    now = now or utcnow()
    with _lock:
        n = db.session.execute(
            update(Auction).where(Auction.status == "scheduled", Auction.start_time <= now).values(status="active"),
            execution_options={"synchronize_session": False}).rowcount
        db.session.commit()
    return n


def close_auction(auction_id, now=None):
    """Close an ended auction exactly once, create the winner and pending payment, notify both sides.

    Returns a dict describing the outcome, or None if it was not closable (not active, not yet ended,
    or already closed by someone else).
    """
    now = now or utcnow()
    with _lock:
        claimed = db.session.execute(
            update(Auction).where(Auction.id == auction_id, Auction.status == "active", Auction.end_time <= now)
            .values(status="closed"),
            execution_options={"synchronize_session": False}).rowcount
        if claimed != 1:
            db.session.rollback()
            return None

        auction = db.session.get(Auction, auction_id, populate_existing=True)
        product = auction.product
        seller_page = f"/seller/products/{product.id}"
        count = bid_count(auction.id)
        info = {"auction_id": auction.id, "status": "closed", "bid_count": count,
                "winner_mask": None, "winning_amount": None}

        if auction.highest_bidder_id is None:
            notify(product.seller_id, "Auction completed", f'Your auction "{product.title}" ended with no bids.',
                   url=seller_page, email=True)
        else:
            winner = Winner(auction_id=auction.id, buyer_id=auction.highest_bidder_id,
                            winning_amount=auction.current_bid, winning_time=now)
            db.session.add(winner)
            db.session.add(Payment(auction_id=auction.id, buyer_id=auction.highest_bidder_id,
                                   amount=auction.current_bid, payment_status="pending"))
            amount = _money(auction.current_bid)
            name = auction.highest_bidder.name
            notify(auction.highest_bidder_id, "Auction won", f'You won "{product.title}" with a bid of {amount}. Please complete your payment.',
                   url=f"/payments/{auction.id}", email=True)
            notify(auction.highest_bidder_id, "Payment pending", f'Please complete payment of {amount} for "{product.title}".',
                   url=f"/payments/{auction.id}")
            notify(product.seller_id, "Auction completed", f'Your auction "{product.title}" ended with {count} bid(s).',
                   url=seller_page)
            notify(product.seller_id, "Winner selected", f'{name} won "{product.title}" with {amount}.',
                   url=seller_page, email=True)
            info["winner_mask"] = (name[:1] + "***") if name else "***"
            info["winning_amount"] = f"{auction.current_bid:.2f}"
        db.session.commit()
        return info


def close_due(now=None):
    """Close every auction whose end time has passed. Returns the list of outcome dicts."""
    now = now or utcnow()
    ids = [i for (i,) in db.session.query(Auction.id).filter(Auction.status == "active", Auction.end_time <= now)]
    return [info for info in (close_auction(i, now) for i in ids) if info]


def notify_ending_soon(now=None):
    """Tell the seller, bidders and watchers once when an active auction is close to its end."""
    now = now or utcnow()
    soon = now + timedelta(minutes=current_app.config["ENDING_SOON_MINUTES"])
    ids = [i for (i,) in db.session.query(Auction.id).filter(
        Auction.status == "active", Auction.ending_notified.is_(False), Auction.end_time > now, Auction.end_time <= soon)]
    sent = 0
    for auction_id in ids:
        with _lock:
            claimed = db.session.execute(
                update(Auction).where(Auction.id == auction_id, Auction.ending_notified.is_(False))
                .values(ending_notified=True), execution_options={"synchronize_session": False}).rowcount
            if claimed != 1:
                db.session.rollback()
                continue
            auction = db.session.get(Auction, auction_id, populate_existing=True)
            product = auction.product
            minutes = max(1, -(-int((auction.end_time - now).total_seconds()) // 60))  # round up
            text = f'The auction for "{product.title}" ends in about {minutes} minute(s).'
            interested = ({b for (b,) in db.session.query(Bid.buyer_id).filter_by(auction_id=auction_id)}
                          | {u for (u,) in db.session.query(Watchlist.user_id).filter_by(product_id=product.id)})
            interested.discard(product.seller_id)
            for uid in interested:
                notify(uid, "Auction ending soon", text, url=f"/auctions/{auction_id}", email=True)
            notify(product.seller_id, "Auction ending soon", text, url=f"/seller/products/{product.id}", email=True)
            db.session.commit()
            sent += 1
    return sent


def run_maintenance(now=None):
    """One scheduler tick: start due auctions, warn about ending ones, close finished ones."""
    now = now or utcnow()
    activate_due(now)
    notify_ending_soon(now)
    payment_service.settle_due(now)
    return close_due(now)
