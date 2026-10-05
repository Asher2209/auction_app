from datetime import datetime, timezone

from ..extensions import db, login_manager


def utcnow():
    """Naive UTC timestamp (portable across SQLite and MySQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


from .user import User  # noqa: E402
from .catalog import Category, Product, ProductImage, Watchlist  # noqa: E402
from .product_details import ProductDetails  # noqa: E402
from .auction import Auction, Bid, Winner  # noqa: E402
from .payment import Payment, CryptoPayment, Invoice  # noqa: E402
from .misc import Notification, NotificationPreference, Review, Feedback  # noqa: E402
from .messaging import Message  # noqa: E402


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    # A deactivated account is logged out on its next request.
    return user if user is not None and user.is_active_user else None


__all__ = [
    "User", "Category", "Product", "ProductImage", "ProductDetails", "Watchlist",
    "Auction", "Bid", "Winner", "Payment", "CryptoPayment", "Invoice",
    "Notification", "NotificationPreference", "Review", "Feedback", "Message", "utcnow",
]
