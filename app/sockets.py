"""Socket.IO: one room per auction. Browsers join to receive live bid and closing events.

Bids themselves are submitted over HTTP (CSRF-protected, server-validated); the server then
broadcasts the result here. Payloads never include real names, only a masked bidder label.
"""
from flask_login import current_user
from flask_socketio import emit, join_room, leave_room

from .extensions import socketio
from .services import auction_service, blockchain_service
from .services.catalog import visible_auctions
from .services.notifications import user_room


def room(auction_id):
    return f"auction_{auction_id}"


def emit_bid(result, auction):
    """Broadcast an accepted bid (and the new end time if anti-sniping extended it)."""
    state = auction_service.auction_state(auction)
    buyer = result.bid.buyer
    state.update({
        "bidder_id": result.bid.buyer_id,
        "bidder_mask": (buyer.name[:1] + "***") if buyer.name else "***",
        "amount": f"{result.bid.amount:.2f}",
        "bid_time": auction_service.iso(result.bid.bid_time),
        "extended": result.extended,
    })
    socketio.emit("bid_update", state, to=room(result.auction_id))
    return state


def emit_closed(info):
    socketio.emit("auction_closed", info, to=room(info["auction_id"]))


@socketio.on("connect")
def on_connect():
    """Signed-in users also join a private room for their own notifications."""
    if current_user.is_authenticated:
        join_room(user_room(current_user.id))


@socketio.on("join")
def on_join(data):
    try:
        auction_id = int((data or {}).get("auction_id"))
    except (TypeError, ValueError):
        emit("error", {"message": "Invalid auction."})
        return
    if visible_auctions().filter_by(id=auction_id).first() is None:
        emit("error", {"message": "Auction not found."})
        return
    join_room(room(auction_id))
    emit("joined", {"auction_id": auction_id})


@socketio.on("leave")
def on_leave(data):
    try:
        leave_room(room(int((data or {}).get("auction_id"))))
    except (TypeError, ValueError):
        pass


def scheduler_loop(app):
    """Background tick: start due auctions and close finished ones, announcing each close."""
    interval = app.config["SCHEDULER_INTERVAL_SECONDS"]
    while True:
        try:
            with app.app_context():
                for info in auction_service.run_maintenance():
                    emit_closed(info)
                blockchain_service.verify_pending()
        except Exception:  # keep ticking; a bad cycle must not kill the loop
            app.logger.exception("Auction scheduler tick failed")
        socketio.sleep(interval)


_started = False


def start_scheduler(app):
    global _started
    if _started:
        return
    _started = True
    socketio.start_background_task(scheduler_loop, app)
