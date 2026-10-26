from ..extensions import db
from . import utcnow


class Auction(db.Model):
    __tablename__ = "auctions"
    __table_args__ = (db.Index("ix_auction_status_end", "status", "end_time"),)

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), unique=True, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    original_end_time = db.Column(db.DateTime, nullable=False)
    extension_count = db.Column(db.Integer, nullable=False, default=0)
    current_bid = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    highest_bidder_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    # scheduled / active / closed / cancelled
    status = db.Column(db.String(10), nullable=False, default="scheduled")
    # set once the "ending soon" notices have gone out, so they are sent only once
    ending_notified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # The lowest price the seller will sell at: below it the auction ends without a sale. Never shown, only "met or not".
    reserve_price = db.Column(db.Numeric(12, 2))
    # Buy the card at once for this price, while nobody has bid yet.
    buy_now_price = db.Column(db.Numeric(12, 2))

    product = db.relationship("Product", backref=db.backref("auction", uselist=False))
    highest_bidder = db.relationship("User", foreign_keys=[highest_bidder_id])
    bids = db.relationship("Bid", backref="auction", order_by="Bid.amount.desc()")


class Bid(db.Model):
    __tablename__ = "bids"
    __table_args__ = (db.Index("ix_bid_auction_amount", "auction_id", "amount"),)

    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(db.Integer, db.ForeignKey("auctions.id"), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    bid_time = db.Column(db.DateTime, nullable=False, default=utcnow)
    is_auto = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())  # placed by a maximum bid

    buyer = db.relationship("User")


class Winner(db.Model):
    __tablename__ = "winners"

    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(db.Integer, db.ForeignKey("auctions.id"), unique=True, nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    winning_amount = db.Column(db.Numeric(12, 2), nullable=False)
    winning_time = db.Column(db.DateTime, nullable=False, default=utcnow)

    auction = db.relationship("Auction", backref=db.backref("winner", uselist=False))
    buyer = db.relationship("User")


class MaxBid(db.Model):
    """The most a bidder is willing to pay (automatic bidding). Secret: only its owner ever sees it. The site bids for
    them, one step above whoever outbids them, until this maximum is reached (services/auction_service.place_bid)."""
    __tablename__ = "max_bids"
    __table_args__ = (db.UniqueConstraint("auction_id", "buyer_id", name="uq_max_bid_auction_buyer"),)

    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(db.Integer, db.ForeignKey("auctions.id"), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    max_amount = db.Column(db.Numeric(12, 2), nullable=False)
    set_at = db.Column(db.DateTime, nullable=False, default=utcnow)  # earlier maximum wins a tie
