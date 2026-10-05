from ..extensions import db
from .user import User
from .catalog import Product
from . import utcnow


class Message(db.Model):
    """Message between buyer and seller about an auction/product."""
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_time = db.Column(db.DateTime, nullable=False, default=utcnow)
    read_time = db.Column(db.DateTime, nullable=True)  # None if unread

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_messages")
    recipient = db.relationship("User", foreign_keys=[recipient_id], backref="received_messages")
    product = db.relationship("Product", backref="messages")

    def is_read(self):
        return self.read_time is not None

    def mark_read(self):
        if not self.is_read():
            self.read_time = utcnow()
            db.session.commit()
