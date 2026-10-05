from datetime import timedelta

from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import TextAreaField
from wtforms.validators import DataRequired, Length

from ...extensions import db
from ...models import Auction, Category, Feedback, utcnow
from ... import sockets
from ...services import auction_service
from ...services import review_service as rs
from ...services.catalog import bid_counts
from . import bp


@bp.route("/")
def index():
    for info in auction_service.run_maintenance():
        sockets.emit_closed(info)
    live = (
        Auction.query.filter_by(status="active")
        .order_by(Auction.end_time.asc())
        .limit(8)
        .all()
    )
    categories = Category.query.order_by(Category.name).all()
    return render_template("index.html", auctions=live, categories=categories,
                           counts=bid_counts([a.id for a in live]),
                           ratings=rs.stats_for_products([a.product_id for a in live]))


@bp.route("/dashboard")
@login_required
def dashboard():
    endpoint = {"admin": "admin.dashboard", "seller": "seller.dashboard", "buyer": "buyer.dashboard"}
    return redirect(url_for(endpoint[current_user.role]))


@bp.route("/health")
def health():
    return {"status": "ok"}


class FeedbackForm(FlaskForm):
    message = TextAreaField("Your feedback", validators=[DataRequired(), Length(min=10, max=1000)])


FEEDBACK_PER_DAY = 10


@bp.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    form = FeedbackForm()
    if form.validate_on_submit():
        since = utcnow() - timedelta(hours=24)
        recent = Feedback.query.filter(Feedback.user_id == current_user.id, Feedback.created_at > since).count()
        if recent >= FEEDBACK_PER_DAY:
            flash("You have sent a lot of feedback today. Please try again tomorrow.", "warning")
        else:
            db.session.add(Feedback(user_id=current_user.id, message=form.message.data.strip()))
            db.session.commit()
            flash("Thank you! Your feedback was sent to the administrators.", "success")
            return redirect(url_for("main.feedback"))
    return render_template("feedback.html", form=form)


@bp.route("/privacy-policy")
def privacy_policy():
    return render_template("legal/privacy_policy.html")


@bp.route("/terms-of-service")
def terms_of_service():
    return render_template("legal/terms_of_service.html")


@bp.route("/refund-policy")
def refund_policy():
    return render_template("legal/refund_policy.html")


@bp.route("/cookie-policy")
def cookie_policy():
    return render_template("legal/cookie_policy.html")
