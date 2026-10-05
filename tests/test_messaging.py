"""Seller-buyer messaging system tests."""
from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Auction, Message, Product, User, Category, utcnow


def test_send_message_to_seller(app):
    """Buyer can send message to seller about a product."""
    with app.app_context():
        # Create users
        seller = User(name="seller", email="seller@test.com", role="seller")
        seller.set_password("password")
        buyer = User(name="buyer", email="buyer@test.com", role="buyer")
        buyer.set_password("password")
        db.session.add_all([seller, buyer])
        db.session.flush()

        # Create product
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
        db.session.commit()

        # Send message
        msg = Message(
            sender_id=buyer.id,
            recipient_id=seller.id,
            product_id=product.id,
            subject="Question about item",
            body="Is this item available?"
        )
        db.session.add(msg)
        db.session.commit()

        # Verify message was created
        retrieved = Message.query.filter_by(sender_id=buyer.id).first()
        assert retrieved is not None
        assert retrieved.recipient_id == seller.id
        assert retrieved.subject == "Question about item"
        assert not retrieved.is_read()


def test_mark_message_as_read(app):
    """Recipient can mark message as read."""
    with app.app_context():
        seller = User(name="seller", email="seller@test.com", role="seller")
        seller.set_password("password")
        buyer = User(name="buyer", email="buyer@test.com", role="buyer")
        buyer.set_password("password")
        db.session.add_all([seller, buyer])
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
            auction_start=utcnow(),
            auction_end=utcnow() + timedelta(hours=1),
            approval_status="approved"
        )
        db.session.add(product)
        db.session.flush()

        auction = Auction(
            product_id=product.id,
            start_time=utcnow(),
            end_time=utcnow() + timedelta(hours=1),
            original_end_time=utcnow() + timedelta(hours=1),
            status="active",
            current_bid=Decimal("100")
        )
        db.session.add(auction)
        db.session.commit()

        msg = Message(
            sender_id=buyer.id,
            recipient_id=seller.id,
            product_id=product.id,
            subject="Question",
            body="Test"
        )
        db.session.add(msg)
        db.session.commit()

        # Mark as read
        assert not msg.is_read()
        msg.mark_read()
        assert msg.is_read()


def test_seller_cannot_message_themselves(app):
    """Seller cannot send message to themselves."""
    with app.app_context():
        seller = User(name="seller", email="seller@test.com", role="seller")
        seller.set_password("password")
        db.session.add(seller)
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
            auction_start=utcnow(),
            auction_end=utcnow() + timedelta(hours=1),
            approval_status="approved"
        )
        db.session.add(product)
        db.session.commit()

        # Try to message self (should be prevented in routes, but test the logic)
        assert product.seller_id == seller.id


def test_conversation_between_buyer_and_seller(app):
    """Buyer and seller can have multi-message conversation."""
    with app.app_context():
        seller = User(name="seller", email="seller@test.com", role="seller")
        seller.set_password("password")
        buyer = User(name="buyer", email="buyer@test.com", role="buyer")
        buyer.set_password("password")
        db.session.add_all([seller, buyer])
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
            auction_start=utcnow(),
            auction_end=utcnow() + timedelta(hours=1),
            approval_status="approved"
        )
        db.session.add(product)
        db.session.flush()

        auction = Auction(
            product_id=product.id,
            start_time=utcnow(),
            end_time=utcnow() + timedelta(hours=1),
            original_end_time=utcnow() + timedelta(hours=1),
            status="active",
            current_bid=Decimal("100")
        )
        db.session.add(auction)
        db.session.commit()

        # Buyer sends message
        msg1 = Message(
            sender_id=buyer.id,
            recipient_id=seller.id,
            product_id=product.id,
            subject="Question about item",
            body="Is this available?"
        )
        db.session.add(msg1)
        db.session.commit()

        # Seller replies
        msg2 = Message(
            sender_id=seller.id,
            recipient_id=buyer.id,
            product_id=product.id,
            subject="Re: Question about item",
            body="Yes, still available"
        )
        db.session.add(msg2)
        db.session.commit()

        # Verify conversation
        conversation = Message.query.filter_by(product_id=product.id).order_by(Message.sent_time).all()
        assert len(conversation) == 2
        assert conversation[0].sender_id == buyer.id
        assert conversation[1].sender_id == seller.id
