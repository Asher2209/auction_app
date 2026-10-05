"""Send email notifications to buyers: outbid alerts and ending-soon reminders."""
from flask import render_template_string
from flask_mail import Message

from ..extensions import mail, db
from ..models import Auction, NotificationPreference, User, utcnow
from ..timeutil import fmt


def send_outbid_email(auction, outbid_buyer):
    """Notify the previous highest bidder that they've been outbid.

    Called when a new bid is placed. The outbid_buyer is the user who had the previous highest bid.
    """
    if not outbid_buyer.email:
        return False

    # Check if user wants outbid notifications
    pref = NotificationPreference.query.get(outbid_buyer.id)
    if pref and not pref.notify_outbid:
        return False

    product = auction.product
    seller = product.seller

    subject = f"You've been outbid on {product.title}"
    body = render_template_string('''
You've been outbid on {{ product.title }} in the {{ category.name }} category.

Current bid: {{ auction.current_bid|money }}
Time remaining: {{ auction.end_time|time_left }}

Place a new bid: {{ url }}

---
ChainBid
''', product=product, category=product.category, auction=auction, url=f"http://localhost:5000/auctions/{auction.id}")

    msg = Message(subject, recipients=[outbid_buyer.email], body=body)
    try:
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Failed to send outbid email to {outbid_buyer.email}: {e}")
        return False


def send_ending_soon_emails():
    """Send notifications to all bidders on auctions ending in the next hour.

    Called by the background scheduler. Sends once per auction to each bidder
    who has not yet received the notification.
    """
    # Find auctions ending in the next hour that haven't had notifications sent yet
    from datetime import timedelta
    now = utcnow()
    soon = now + timedelta(hours=1)

    auctions = Auction.query.filter(
        Auction.status == "active",
        Auction.end_time.between(now, soon),
        ~Auction.ending_notified  # Haven't sent notifications yet
    ).all()

    count = 0
    for auction in auctions:
        # Send to all unique bidders on this auction
        bidders = db.session.query(User).join(
            Auction.bids
        ).filter(
            Auction.id == auction.id
        ).distinct().all()

        product = auction.product

        for bidder in bidders:
            # Check if user wants ending soon notifications
            pref = NotificationPreference.query.get(bidder.id)
            if pref and not pref.notify_ending_soon:
                continue

            if not bidder.email:
                continue

            subject = f"Auction ending soon: {product.title}"
            body = render_template_string('''
{{ product.title }} will end in about 1 hour.

Current bid: {{ auction.current_bid|money }}
Ending at: {{ auction.end_time|local }}

Place your bid: {{ url }}

---
ChainBid
''', product=product, auction=auction, url=f"http://localhost:5000/auctions/{auction.id}")

            msg = Message(subject, recipients=[bidder.email], body=body)
            try:
                mail.send(msg)
                count += 1
            except Exception as e:
                print(f"Failed to send ending-soon email to {bidder.email}: {e}")

        # Mark this auction as having sent notifications
        auction.ending_notified = True

    db.session.commit()
    return count


def create_default_preferences(user):
    """Create notification preferences for a new user (defaults to all enabled)."""
    pref = NotificationPreference(user_id=user.id, notify_outbid=True, notify_ending_soon=True)
    db.session.add(pref)
    db.session.commit()
