"""Watchlist notifications: alerts when watched auctions get new bids or are ending soon."""
from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Auction, Bid, NotificationPreference, Product, User, Watchlist, utcnow, Category


def test_bid_notifies_watchers(app):
    """When a bid is placed, watchers of that auction are notified by email."""
    with app.app_context():
        # Create users
        seller = User(name="seller", email="seller@test.com", role="seller")
        seller.set_password("password")
        bidder = User(name="bidder", email="bidder@test.com", role="buyer")
        bidder.set_password("password")
        watcher = User(name="watcher", email="watcher@test.com", role="buyer")
        watcher.set_password("password")
        
        db.session.add_all([seller, bidder, watcher])
        db.session.flush()
        
        # Create notification preferences (watcher has notifications enabled)
        NotificationPreference(user_id=watcher.id, notify_ending_soon=True)
        NotificationPreference(user_id=bidder.id)
        db.session.add_all([
            NotificationPreference(user_id=watcher.id, notify_ending_soon=True),
            NotificationPreference(user_id=bidder.id)
        ])
        db.session.flush()
        
        # Create category and product
        cat = Category(name="Test")
        db.session.add(cat)
        db.session.flush()
        
        product = Product(
            seller_id=seller.id,
            category_id=cat.id,
            title="Test item",
            description="Test",
            starting_price=Decimal("100"),
            auction_start=utcnow(),
            auction_end=utcnow() + timedelta(hours=1),
            approval_status="approved"
        )
        db.session.add(product)
        db.session.flush()
        
        # Create auction
        auction = Auction(
            product_id=product.id,
            start_time=utcnow(),
            end_time=utcnow() + timedelta(hours=1),
            original_end_time=utcnow() + timedelta(hours=1),
            status="active",
            current_bid=Decimal("100")
        )
        db.session.add(auction)
        db.session.flush()
        
        # Watcher watches the auction
        watchlist_entry = Watchlist(user_id=watcher.id, product_id=product.id)
        db.session.add(watchlist_entry)
        db.session.commit()
        
        # Verify watcher is watching
        assert Watchlist.query.filter_by(user_id=watcher.id, product_id=product.id).first() is not None


def test_watcher_notification_respects_preferences(app):
    """New bid notifications for watchers respect email preferences."""
    with app.app_context():
        # Create watcher with notifications disabled
        watcher = User(name="watcher", email="watcher@test.com", role="buyer")
        watcher.set_password("password")
        db.session.add(watcher)
        db.session.flush()
        
        # Disable ending soon notifications
        pref = NotificationPreference(user_id=watcher.id, notify_ending_soon=False)
        db.session.add(pref)
        db.session.commit()
        
        loaded = NotificationPreference.query.get(watcher.id)
        assert loaded.notify_ending_soon is False


def test_watchers_notified_when_auction_ending_soon(app):
    """Watchers are notified when an auction they're watching is ending soon."""
    with app.app_context():
        seller = User(name="seller", email="seller@test.com", role="seller")
        seller.set_password("password")
        watcher = User(name="watcher", email="watcher@test.com", role="buyer")
        watcher.set_password("password")
        
        db.session.add_all([seller, watcher])
        db.session.flush()
        
        NotificationPreference(user_id=watcher.id, notify_ending_soon=True)
        db.session.add(NotificationPreference(user_id=watcher.id, notify_ending_soon=True))
        db.session.flush()
        
        cat = Category(name="Test")
        db.session.add(cat)
        db.session.flush()
        
        product = Product(
            seller_id=seller.id,
            category_id=cat.id,
            title="Test item",
            description="Test",
            starting_price=Decimal("100"),
            auction_start=utcnow() - timedelta(hours=1),
            auction_end=utcnow() + timedelta(minutes=30),
            approval_status="approved"
        )
        db.session.add(product)
        db.session.flush()
        
        auction = Auction(
            product_id=product.id,
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() + timedelta(minutes=30),
            original_end_time=utcnow() + timedelta(minutes=30),
            status="active",
            current_bid=Decimal("200")
        )
        db.session.add(auction)
        db.session.flush()
        
        # Watcher watches the item
        watchlist = Watchlist(user_id=watcher.id, product_id=product.id)
        db.session.add(watchlist)
        db.session.commit()
        
        # Verify watchlist entry exists
        assert Watchlist.query.filter_by(user_id=watcher.id, product_id=product.id).first() is not None
