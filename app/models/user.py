from flask_login import UserMixin
from sqlalchemy import event
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from . import utcnow

ROLES = ("buyer", "seller", "admin")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(30))
    address = db.Column(db.Text)
    role = db.Column(db.String(10), nullable=False, default="buyer")
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    # Set only by proving control of the wallet (a signed one-time message, see wallet_service). One account per wallet.
    wallet_address = db.Column(db.String(42), unique=True)
    wallet_verified_at = db.Column(db.DateTime)  # when control of wallet_address was proven
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):  # Flask-Login hook
        return self.is_active_user

    def has_role(self, *roles):
        return self.role in roles

    @property
    def has_verified_wallet(self):
        return bool(self.wallet_address) and self.wallet_verified_at is not None

    @property
    def verified_wallet(self):
        """The wallet this user has proven they control, or None. Money and tokens only ever go to this address."""
        return self.wallet_address if self.has_verified_wallet else None

    def link_wallet(self, address, when=None):
        """Record proven control of `address` (already checksummed). Requests go through wallet_service.finish."""
        self.wallet_address = address
        self.wallet_verified_at = when or utcnow()

    def unlink_wallet(self):
        self.wallet_address = None
        self.wallet_verified_at = None


@event.listens_for(User.wallet_address, "set", active_history=True)
def _wallet_changed(target, value, oldvalue, initiator):
    """An address set any other way than link_wallet() has not been proven, so it must not count as verified."""
    if value != oldvalue:
        target.wallet_verified_at = None
