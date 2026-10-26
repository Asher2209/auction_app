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
from sqlalchemy import and_, func, update

from ..extensions import db
from ..models import Auction, Bid, MaxBid, Payment, Watchlist, Winner, utcnow
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
    new_bids: list = None  # this bid, then any automatic bids it set off, in order


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


def bid_increment(price):
    """How much the next bid must beat `price` by (Config.BID_INCREMENTS: the step grows with the price)."""
    step = None
    for start, increment in current_app.config["BID_INCREMENTS"]:
        if price >= start:
            step = increment
    return step


def min_next_bid(auction):
    """First bid may equal the starting price; every later bid must beat the current one by the step for its price."""
    if auction.highest_bidder_id is None:
        return auction.current_bid
    return auction.current_bid + bid_increment(auction.current_bid)


def reserve_met(auction):
    """True when there is no reserve, or the current bid has reached it. The reserve itself is never shown."""
    return auction.reserve_price is None or (auction.highest_bidder_id is not None and auction.current_bid >= auction.reserve_price)


def buy_now_open(auction):
    """Buy It Now is offered until the first bid."""
    return auction.buy_now_price is not None and auction.highest_bidder_id is None and auction.status == "active"


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
        "bid_step": f"{bid_increment(auction.current_bid):.2f}",
        "has_reserve": auction.reserve_price is not None,
        "reserve_met": reserve_met(auction),
        "buy_now_price": f"{auction.buy_now_price:.2f}" if buy_now_open(auction) else None,
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


def own_maximum(auction, user):
    """The maximum `user` set on this auction, if any: shown to them alone."""
    if not getattr(user, "is_authenticated", False):
        return None
    mx = MaxBid.query.filter_by(auction_id=auction.id, buyer_id=user.id).first()
    return mx.max_amount if mx else None


def _ceiling(auction, user_id):
    """What `user_id` will pay at most in this auction: their maximum bid if they set one, else their highest bid."""
    mx = MaxBid.query.filter_by(auction_id=auction.id, buyer_id=user_id).first()
    top = db.session.query(func.max(Bid.amount)).filter_by(auction_id=auction.id, buyer_id=user_id).scalar() or Decimal(0)
    return max(mx.max_amount, top) if mx else top


def _resolve(auction, user_id, amount, ceiling):
    """Who leads, and at what price, after `user_id` bids `amount` and will go up to `ceiling` (>= amount).

    Returns (leader_id, price, extra) where extra lists the automatic bids to record, as (bidder_id, amount).
    The rule is the usual one: whoever is willing to pay more leads, one step above the other's limit, never above
    their own; on a tie the earlier limit wins. A leader's limit at or above the reserve lifts the price to the reserve.
    """
    leader = auction.highest_bidder_id
    extra = []
    if leader is None or leader == user_id:  # first bid, or the leader raising their own bid
        leader_id, price, leader_ceiling = user_id, amount, ceiling
    else:
        rival = _ceiling(auction, leader)
        if ceiling > rival:
            leader_id, leader_ceiling = user_id, ceiling
            price = max(amount, min(ceiling, rival + bid_increment(rival)))
            if rival > auction.current_bid:
                extra.append((leader, rival))  # the outbid limit was fought for in full
        else:
            leader_id, leader_ceiling = leader, rival
            if ceiling > amount:
                extra.append((user_id, ceiling))  # the challenger's own limit, spent
            price = rival if ceiling == rival else min(rival, ceiling + bid_increment(ceiling))
    if auction.reserve_price is not None and price < auction.reserve_price <= leader_ceiling:
        price = auction.reserve_price
    if leader_id != user_id or price > amount:
        extra.append((leader_id, price))
    return leader_id, price, extra


def place_bid(auction_id, user, raw_amount, now=None, raw_max=None):
    """Validate and record a bid, with an optional maximum (automatic bidding). Raises BidError on any rule failure.

    `raw_amount` is placed as it is; `raw_max`, if given, is the most the bidder will pay: from then on the site bids
    for them, one step above any rival, up to that limit. Nobody else ever learns a maximum.
    """
    now = now or utcnow()
    amount = parse_amount(raw_amount)
    maximum = parse_amount(raw_max) if raw_max not in (None, "") else None
    if maximum is not None and maximum < amount:
        raise BidError("Your maximum must be at least your bid.")
    if user.role != "member":
        raise BidError("Admin accounts cannot place bids.", 403)
    if not user.email_verified:
        raise BidError("Confirm your email address before you bid: open the link we emailed you, or send a new one from the banner.", 403)

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

            own = MaxBid.query.filter_by(auction_id=auction.id, buyer_id=user.id).first()
            ceiling = max(amount, maximum if maximum is not None else (own.max_amount if own else amount))
            leader_id, price, autos = _resolve(auction, user.id, amount, ceiling)

            same_bidder = (Auction.highest_bidder_id.is_(None) if previous_bidder is None
                           else Auction.highest_bidder_id == previous_bidder)
            values = {"current_bid": price, "highest_bidder_id": leader_id, "end_time": new_end}
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
            new_bids = [bid]
            for bidder_id, auto_amount in autos:  # recorded after the bid that caused them, in order
                auto = Bid(auction_id=auction.id, buyer_id=bidder_id, amount=auto_amount, bid_time=now, is_auto=True)
                db.session.add(auto)
                new_bids.append(auto)
            if maximum is not None:
                if own is None:
                    db.session.add(MaxBid(auction_id=auction.id, buyer_id=user.id, max_amount=maximum, set_at=now))
                elif maximum != own.max_amount:
                    own.max_amount, own.set_at = maximum, now
            title = auction.product.title
            page = f"/auctions/{auction.id}"
            seller_page = f"/seller/products/{auction.product_id}"
            if leader_id == user.id:
                notify(user.id, "Bid accepted", f'You are the highest bidder on "{title}" at {_money(price)}.', url=page)
                if previous_bidder and previous_bidder != user.id:
                    notify(previous_bidder, "You have been outbid",
                           f'Someone placed a higher bid ({_money(price)}) on "{title}".', url=page, email=True)
            else:
                notify(user.id, "You have been outbid",
                       f'Your bid on "{title}" was beaten at once by another bidder\'s automatic bid: the price is now {_money(price)}.',
                       url=page, email=True)
                notify(leader_id, "Your automatic bid kept you ahead",
                       f'Your maximum bid on "{title}" kept you the highest bidder, now at {_money(price)}.', url=page)
            notify(auction.product.seller_id, "New bid received", f'The bid on "{title}" is now {_money(price)}.', url=seller_page)

            # Notify watchers of this auction that a new bid was placed
            from ..models import Watchlist
            watchers = db.session.query(Watchlist.user_id).filter_by(product_id=auction.product_id).all()
            for (watcher_id,) in watchers:
                if watcher_id not in (user.id, leader_id):  # the bidders have already been told
                    notify(watcher_id, "New bid on watched item",
                           f'The highest bid on "{title}" is now {_money(price)}.', url=page, email=True)
            db.session.commit()
            db.session.refresh(auction)
            return BidResult(auction.id, bid, previous_bidder, extended, new_bids)

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
        elif not reserve_met(auction):  # nobody bid enough: no sale, no payment
            info["reserve_not_met"] = True
            notify(product.seller_id, "Reserve not met",
                   f'Your auction "{product.title}" ended at {_money(auction.current_bid)}, below your reserve price, so the card is not sold.',
                   url=seller_page, email=True)
            notify(auction.highest_bidder_id, "Auction ended without a sale",
                   f'The auction for "{product.title}" ended below the seller\'s reserve price, so it was not sold.',
                   url=f"/auctions/{auction.id}", email=True)
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


def buy_now(auction_id, user, now=None):
    """Buy the card at its Buy It Now price: possible until the first bid. Ends the auction with `user` as the winner,
    exactly as if they had won it at that price (the same winner, payment and notices). Raises BidError otherwise."""
    now = now or utcnow()
    if user.role != "member":
        raise BidError("Admin accounts cannot buy.", 403)
    if not user.email_verified:
        raise BidError("Confirm your email address before you buy: open the link we emailed you, or send a new one from the banner.", 403)
    with _lock:
        activate_due(now)
        auction = db.session.get(Auction, auction_id, populate_existing=True)
        _check_open(auction, user, now)
        if not buy_now_open(auction):
            raise BidError("Buy It Now is no longer available: bidding has started.", 409)
        price = auction.buy_now_price
        claimed = db.session.execute(  # only while still nobody has bid; ending now lets the normal close finish it
            update(Auction).where(Auction.id == auction.id, Auction.status == "active", Auction.highest_bidder_id.is_(None))
            .values(current_bid=price, highest_bidder_id=user.id, end_time=now),
            execution_options={"synchronize_session": False}).rowcount
        if claimed != 1:
            db.session.rollback()
            raise BidError("Someone else bid or bought it a moment ago.", 409)
        db.session.add(Bid(auction_id=auction.id, buyer_id=user.id, amount=price, bid_time=now))
        db.session.commit()
    info = close_auction(auction_id, now)
    if info is None:  # cannot happen while we hold the claim, but never report a sale that did not close
        raise BidError("The purchase could not be completed. Please try again.", 409)
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
