"""Ratings and reviews.

Rules
* Only the buyer who actually paid for an item may review it ("verified purchase"), once per product.
  They may edit or delete their review.
* A hidden review (moderated by an admin) is excluded from everything public and from the averages,
  and its author cannot edit it back into view.
* Ratings are whole numbers 1-5. Comments are optional, trimmed, at most MAX_COMMENT characters.
"""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Auction, Payment, Product, Review, utcnow
from .notifications import notify

MAX_COMMENT = 1000


class ReviewError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def paid_payment(user, auction_id):
    """The user's successful payment for this auction, or None."""
    return Payment.query.filter_by(auction_id=auction_id, buyer_id=user.id, payment_status="successful").first()


def can_review(user, auction_id):
    return user.is_authenticated and user.role == "buyer" and paid_payment(user, auction_id) is not None


def parse_rating(raw):
    text = raw.strip() if isinstance(raw, str) else ""
    if text not in {"1", "2", "3", "4", "5"}:  # whole numbers only: no "3.5", " 03", "+4" or non-ASCII digits
        raise ReviewError("Choose a rating from 1 to 5 stars.")
    return int(text)


def parse_comment(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ReviewError("The review text is not valid.")
    text = raw.strip().replace("\r\n", "\n")
    if len(text) > MAX_COMMENT:
        raise ReviewError(f"Please keep your review under {MAX_COMMENT} characters.")
    return text or None


def own_review(user, product_id):
    return Review.query.filter_by(product_id=product_id, buyer_id=user.id).first()


def save_review(user, auction_id, raw_rating, raw_comment, now=None):
    """Create the buyer's review for an item they paid for, or update it. Returns (review, created)."""
    now = now or utcnow()
    rating, comment = parse_rating(raw_rating), parse_comment(raw_comment)
    payment = paid_payment(user, auction_id) if user.role == "buyer" else None
    if payment is None:
        raise ReviewError("You can review an item once you have paid for it.", 403)
    product = payment.auction.product

    review = own_review(user, product.id)
    created = review is None
    if review is not None and review.is_hidden:
        raise ReviewError("This review was hidden by a moderator and can no longer be edited.", 403)
    if created:
        review = Review(product_id=product.id, buyer_id=user.id, rating=rating, comment=comment, created_at=now)
        db.session.add(review)
        try:
            db.session.flush()  # the unique (product, buyer) constraint settles simultaneous submissions
        except IntegrityError:
            db.session.rollback()
            review = own_review(user, product.id)
            if review is None:
                raise
            created = False
    if not created:
        if review.is_hidden:
            raise ReviewError("This review was hidden by a moderator and can no longer be edited.", 403)
        review.rating, review.comment, review.updated_at = rating, comment, now
    if created:
        notify(product.seller_id, "New review",
               f'{"★" * rating} A buyer reviewed "{product.title}".', url=f"/seller/products/{product.id}")
    db.session.commit()
    return review, created


def delete_own_review(user, auction_id):
    payment = Payment.query.filter_by(auction_id=auction_id, buyer_id=user.id).first()
    review = own_review(user, payment.auction.product_id) if payment else None
    if review is None:
        raise ReviewError("You have not reviewed this item.", 404)
    if review.is_hidden:  # otherwise a hidden review could be deleted and re-posted to dodge moderation
        raise ReviewError("This review was hidden by a moderator, so it cannot be deleted or replaced.", 403)
    db.session.delete(review)
    db.session.commit()


# ---- statistics (visible reviews only) -------------------------------------------------
def stats_for_products(product_ids):
    """{product_id: (average rounded to 1 decimal, count)} for products that have visible reviews."""
    if not product_ids:
        return {}
    rows = (db.session.query(Review.product_id, func.avg(Review.rating), func.count(Review.id))
            .filter(Review.product_id.in_(list(product_ids)), Review.is_hidden.is_(False))
            .group_by(Review.product_id).all())
    return {pid: (round(float(avg), 1), n) for pid, avg, n in rows}


def seller_stats(seller_id):
    avg, n = (db.session.query(func.avg(Review.rating), func.count(Review.id)).join(Product, Review.product_id == Product.id)
              .filter(Product.seller_id == seller_id, Review.is_hidden.is_(False)).one())
    return (round(float(avg), 1), n) if n else None


def visible_reviews(product_id):
    return (Review.query.filter_by(product_id=product_id, is_hidden=False)
            .order_by(Review.created_at.desc(), Review.id.desc()).all())


# ---- moderation ---------------------------------------------------------------------------
def set_hidden(review, hidden, reason=None):
    review.is_hidden = hidden
    review.hidden_reason = reason if hidden else None
    title = review.product.title
    if hidden:
        notify(review.buyer_id, "Review hidden",
               f'Your review of "{title}" was hidden by a moderator: {reason}')
    else:
        notify(review.buyer_id, "Review restored", f'Your review of "{title}" is visible again.')
    db.session.commit()
