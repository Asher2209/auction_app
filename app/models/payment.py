from ..extensions import db
from . import utcnow


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(db.Integer, db.ForeignKey("auctions.id"), unique=True, nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    # simulated / crypto (null until the buyer chooses)
    payment_method = db.Column(db.String(12))
    # pending / successful / failed
    payment_status = db.Column(db.String(12), nullable=False, default="pending")
    payment_date = db.Column(db.DateTime)
    # Simulated gateway details. Card numbers and CVVs are never stored: only a masked reference.
    method_detail = db.Column(db.String(10))  # card / upi / wallet
    reference = db.Column(db.String(80))  # e.g. "Card **** 4242"
    gateway_ref = db.Column(db.String(30))  # e.g. "SIM-3F9A1C20B7D4"
    failure_reason = db.Column(db.String(200))
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    settle_at = db.Column(db.DateTime)  # a gateway-pending simulated payment settles at this time
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    auction = db.relationship("Auction", backref=db.backref("payment", uselist=False))
    buyer = db.relationship("User")

    @property
    def awaiting_payment(self):
        """True while the buyer has not (successfully) started a payment: first try, or retry after a failure."""
        return self.payment_status == "failed" or (self.payment_status == "pending" and self.payment_method is None)

    @property
    def processing(self):
        return self.payment_status == "pending" and self.payment_method is not None


class CryptoPayment(db.Model):
    __tablename__ = "crypto_payments"
    __table_args__ = (db.UniqueConstraint("payment_id", name="uq_crypto_payments_payment_id"),)

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    wallet_address = db.Column(db.String(42), nullable=False)  # the buyer's wallet
    seller_address = db.Column(db.String(42))  # payout wallet the quote was made for
    contract_address = db.Column(db.String(42))
    exchange_rate = db.Column(db.Numeric(18, 2))  # INR per ETH used for the quote
    cryptocurrency = db.Column(db.String(10), nullable=False, default="ETH")
    expected_wei = db.Column(db.Numeric(38, 0))
    amount = db.Column(db.Numeric(38, 18), nullable=False)
    transaction_hash = db.Column(db.String(66), unique=True)
    blockchain_network = db.Column(db.String(30), nullable=False, default="sepolia")
    chain_id = db.Column(db.Integer)
    block_number = db.Column(db.Integer)
    confirmations = db.Column(db.Integer, default=0)
    # pending / confirmed / failed
    status = db.Column(db.String(10), nullable=False, default="pending")
    failure_reason = db.Column(db.String(255))
    transaction_date = db.Column(db.DateTime, default=utcnow)

    payment = db.relationship("Payment", backref=db.backref("crypto", uselist=False))


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), unique=True, nullable=False)
    number = db.Column(db.String(30), unique=True, nullable=False)
    pdf_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    payment = db.relationship("Payment", backref=db.backref("invoice", uselist=False))
