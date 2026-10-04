from flask_login import UserMixin
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
    wallet_address = db.Column(db.String(42))
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
