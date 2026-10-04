from flask import flash, redirect, request, url_for
from flask_login import current_user

from ...services import review_service as rs
from ...services.review_service import ReviewError
from ...utils import role_required
from . import bp


def _back(auction_id):
    return redirect(url_for("auctions.detail", auction_id=auction_id, _anchor="reviews"))


@bp.route("/<int:auction_id>", methods=["POST"])
@role_required("buyer")
def save(auction_id):
    """Create or update the buyer's review of an item they paid for."""
    try:
        _, created = rs.save_review(current_user, auction_id, request.form.get("rating"), request.form.get("comment"))
    except ReviewError as e:
        flash(e.message, "danger" if e.status == 400 else "warning")
    else:
        flash("Thanks for your review!" if created else "Your review was updated.", "success")
    return _back(auction_id)


@bp.route("/<int:auction_id>/delete", methods=["POST"])
@role_required("buyer")
def delete(auction_id):
    try:
        rs.delete_own_review(current_user, auction_id)
        flash("Your review was deleted.", "info")
    except ReviewError as e:
        flash(e.message, "warning")
    return _back(auction_id)
