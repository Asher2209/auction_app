from datetime import timedelta

from flask import Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from ...extensions import db
from ...models import Auction, Bid, Category, CryptoPayment, Feedback, Product, Review, User, utcnow
from ...services import analytics_service, payment_service, report_export, report_service
from ...services import review_service
from ...services.notifications import notify
from ...utils import like_pattern, role_required, safe_redirect_target
from . import bp
from .forms import CategoryForm, ReasonForm

PER_PAGE = 15
PRODUCT_FILTERS = ("pending", "approved", "rejected", "all")
USER_ROLES = ("all", "buyer", "seller", "admin")


def _product_or_404(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        abort(404)
    return product


@bp.route("/")
@role_required("admin")
def dashboard():
    role_counts = dict(db.session.query(User.role, func.count(User.id)).group_by(User.role).all())
    stats = {
        "users": sum(role_counts.values()),
        "buyers": role_counts.get("buyer", 0),
        "sellers": role_counts.get("seller", 0),
        "pending": Product.query.filter_by(approval_status="pending").count(),
        "products": Product.query.count(),
        "active_auctions": Auction.query.filter(Auction.status.in_(("scheduled", "active"))).count(),
        "completed_auctions": Auction.query.filter_by(status="closed").count(),
        "bids": Bid.query.count(),
        "categories": Category.query.count(),
        "crypto_payments": CryptoPayment.query.filter_by(status="confirmed").count(),
        "pending_payments": payment_service.pending_total(),
        "revenue": payment_service.revenue_total(),
    }
    pending = (Product.query.filter_by(approval_status="pending")
               .order_by(Product.created_at.asc()).limit(5).all())
    return render_template("admin/dashboard.html", stats=stats, pending=pending)


# ---- product moderation -------------------------------------------------
@bp.route("/products")
@role_required("admin")
def products():
    status = request.args.get("status", "pending")
    if status not in PRODUCT_FILTERS:
        status = "pending"
    q = request.args.get("q", "").strip()
    query = Product.query
    if status != "all":
        query = query.filter(Product.approval_status == status)
    if q:
        query = query.filter(Product.title.ilike(like_pattern(q), escape="\\"))
    page = query.order_by(Product.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    return render_template("admin/products.html", page=page, status=status, q=q, filters=PRODUCT_FILTERS)


@bp.route("/products/<int:product_id>")
@role_required("admin")
def product_review(product_id):
    product = _product_or_404(product_id)
    return render_template("admin/product_review.html", product=product, auction=product.auction,
                           form=ReasonForm())


@bp.route("/products/<int:product_id>/approve", methods=["POST"])
@role_required("admin")
def approve_product(product_id):
    product = _product_or_404(product_id)
    if product.approval_status != "pending" or product.auction is not None:
        flash("Only pending listings can be approved.", "warning")
        return redirect(url_for("admin.product_review", product_id=product.id))

    now = utcnow()
    if product.auction_end <= now:
        flash("This listing's auction window has already passed. Ask the seller to reschedule it.", "danger")
        return redirect(url_for("admin.product_review", product_id=product.id))

    product.approval_status = "approved"
    product.rejection_reason = None
    db.session.add(Auction(
        product_id=product.id,
        start_time=product.auction_start,
        end_time=product.auction_end,
        original_end_time=product.auction_end,
        # first bid must be at least the starting price; later bids must beat current_bid
        current_bid=product.starting_price,
        status="active" if product.auction_start <= now else "scheduled",
    ))
    notify(product.seller_id, "Product approved",
           f'Your listing "{product.title}" was approved and the auction is set up.',
           url=f"/seller/products/{product.id}", email=True)
    db.session.commit()
    flash("Listing approved and auction created.", "success")
    return redirect(url_for("admin.products", status="pending"))


@bp.route("/products/<int:product_id>/reject", methods=["POST"])
@role_required("admin")
def reject_product(product_id):
    product = _product_or_404(product_id)
    form = ReasonForm()
    if product.approval_status != "pending":
        flash("Only pending listings can be rejected. Use Remove for live listings.", "warning")
        return redirect(url_for("admin.product_review", product_id=product.id))
    if not form.validate_on_submit():
        flash("Please give a reason of at least 5 characters.", "danger")
        return redirect(url_for("admin.product_review", product_id=product.id))
    product.approval_status = "rejected"
    product.rejection_reason = form.reason.data.strip()
    notify(product.seller_id, "Product rejected",
           f'Your listing "{product.title}" was rejected: {product.rejection_reason}',
           url=f"/seller/products/{product.id}", email=True)
    db.session.commit()
    flash("Listing rejected.", "info")
    return redirect(url_for("admin.products", status="pending"))


@bp.route("/products/<int:product_id>/remove", methods=["POST"])
@role_required("admin")
def remove_product(product_id):
    """Take down a fake or inappropriate listing, including one that is already live."""
    product = _product_or_404(product_id)
    form = ReasonForm()
    auction = product.auction
    if auction is not None and auction.status == "closed":
        flash("Completed auctions have winner and payment records and cannot be removed.", "warning")
        return redirect(url_for("admin.product_review", product_id=product.id))
    if not form.validate_on_submit():
        flash("Please give a reason of at least 5 characters.", "danger")
        return redirect(url_for("admin.product_review", product_id=product.id))

    reason = form.reason.data.strip()
    product.approval_status = "rejected"
    product.rejection_reason = reason
    if auction is not None:
        auction.status = "cancelled"
        bidders = {b.buyer_id for b in auction.bids}
        for buyer_id in bidders:
            notify(buyer_id, "Auction cancelled",
                   f'The auction for "{product.title}" was cancelled by an administrator.', email=True)
    notify(product.seller_id, "Listing removed",
           f'Your listing "{product.title}" was removed by an administrator: {reason}',
           url=f"/seller/products/{product.id}", email=True)
    db.session.commit()
    flash("Listing removed.", "info")
    return redirect(url_for("admin.products", status="all"))


# ---- users ---------------------------------------------------------------
@bp.route("/users")
@role_required("admin")
def users():
    role = request.args.get("role", "all")
    if role not in USER_ROLES:
        role = "all"
    q = request.args.get("q", "").strip()
    query = User.query
    if role != "all":
        query = query.filter(User.role == role)
    if q:
        like = like_pattern(q)
        query = query.filter(User.name.ilike(like, escape="\\") | User.email.ilike(like, escape="\\"))
    page = query.order_by(User.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    return render_template("admin/users.html", page=page, role=role, q=q, roles=USER_ROLES)


@bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@role_required("admin")
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "warning")
    else:
        user.is_active_user = not user.is_active_user
        db.session.commit()
        flash(f"{user.name} is now {'active' if user.is_active_user else 'deactivated'}.", "success")
    return redirect(safe_redirect_target(request.referrer) or url_for("admin.users"))


# ---- categories ----------------------------------------------------------
@bp.route("/categories", methods=["GET", "POST"])
@role_required("admin")
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if Category.query.filter(func.lower(Category.name) == name.lower()).first():
            form.name.errors.append("That category already exists.")
        else:
            db.session.add(Category(name=name))
            db.session.commit()
            flash("Category added.", "success")
            return redirect(url_for("admin.categories"))
    rows = (db.session.query(Category, func.count(Product.id))
            .outerjoin(Product, Product.category_id == Category.id)
            .group_by(Category.id).order_by(Category.name).all())
    return render_template("admin/categories.html", form=form, rows=rows)


@bp.route("/categories/<int:category_id>/rename", methods=["POST"])
@role_required("admin")
def rename_category(category_id):
    cat = db.session.get(Category, category_id) or abort(404)
    form = CategoryForm()
    if not form.validate_on_submit():
        flash("Category name must be 2-80 characters.", "danger")
    else:
        name = form.name.data.strip()
        clash = Category.query.filter(func.lower(Category.name) == name.lower(), Category.id != cat.id).first()
        if clash:
            flash("Another category already uses that name.", "danger")
        else:
            cat.name = name
            db.session.commit()
            flash("Category renamed.", "success")
    return redirect(url_for("admin.categories"))


@bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@role_required("admin")
def delete_category(category_id):
    cat = db.session.get(Category, category_id) or abort(404)
    if Product.query.filter_by(category_id=cat.id).count():
        flash("A category with products cannot be deleted.", "warning")
    else:
        db.session.delete(cat)
        db.session.commit()
        flash("Category deleted.", "info")
    return redirect(url_for("admin.categories"))


# ---- reviews -------------------------------------------------------------
REVIEW_FILTERS = ("all", "visible", "hidden")
ESC = "\\"


@bp.route("/reviews")
@role_required("admin")
def reviews():
    status = request.args.get("status", "all")
    if status not in REVIEW_FILTERS:
        status = "all"
    q = request.args.get("q", "").strip()
    query = Review.query.join(Product, Review.product_id == Product.id).join(User, Review.buyer_id == User.id)
    if status != "all":
        query = query.filter(Review.is_hidden.is_(status == "hidden"))
    if q:
        like = like_pattern(q)
        query = query.filter(Product.title.ilike(like, escape=ESC) | User.name.ilike(like, escape=ESC)
                             | User.email.ilike(like, escape=ESC) | Review.comment.ilike(like, escape=ESC))
    page = query.order_by(Review.created_at.desc(), Review.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    return render_template("admin/reviews.html", page=page, status=status, q=q, filters=REVIEW_FILTERS, form=ReasonForm())


def _review_or_404(review_id):
    review = db.session.get(Review, review_id)
    if review is None:
        abort(404)
    return review


@bp.route("/reviews/<int:review_id>/hide", methods=["POST"])
@role_required("admin")
def hide_review(review_id):
    review = _review_or_404(review_id)
    form = ReasonForm()
    if not form.validate_on_submit():
        flash("Please give a reason of at least 5 characters.", "danger")
    else:
        review_service.set_hidden(review, True, form.reason.data.strip())
        flash("Review hidden.", "info")
    return redirect(url_for("admin.reviews"))


@bp.route("/reviews/<int:review_id>/unhide", methods=["POST"])
@role_required("admin")
def unhide_review(review_id):
    review_service.set_hidden(_review_or_404(review_id), False)
    flash("Review restored.", "success")
    return redirect(url_for("admin.reviews"))


@bp.route("/reviews/<int:review_id>/delete", methods=["POST"])
@role_required("admin")
def delete_review(review_id):
    db.session.delete(_review_or_404(review_id))
    db.session.commit()
    flash("Review deleted.", "info")
    return redirect(url_for("admin.reviews"))


# ---- feedback ------------------------------------------------------------
@bp.route("/feedback")
@role_required("admin")
def feedback():
    q = request.args.get("q", "").strip()
    query = Feedback.query.join(User, Feedback.user_id == User.id)
    if q:
        like = like_pattern(q)
        query = query.filter(Feedback.message.ilike(like, escape=ESC) | User.name.ilike(like, escape=ESC)
                             | User.email.ilike(like, escape=ESC))
    page = query.order_by(Feedback.created_at.desc(), Feedback.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    return render_template("admin/feedback.html", page=page, q=q)


@bp.route("/feedback/<int:feedback_id>/delete", methods=["POST"])
@role_required("admin")
def delete_feedback(feedback_id):
    item = db.session.get(Feedback, feedback_id)
    if item is None:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("Feedback deleted.", "info")
    return redirect(url_for("admin.feedback"))


# ---- analytics -------------------------------------------------------------
@bp.route("/analytics")
@role_required("admin")
def analytics():
    months = analytics_service.parse_months(request.args.get("months"))
    return render_template("admin/analytics.html", months=months, allowed=analytics_service.ALLOWED_MONTHS)


@bp.route("/analytics/data")
@role_required("admin")
def analytics_data():
    """JSON for the charts. Admin only: it contains buyer and seller names."""
    response = jsonify(analytics_service.build(analytics_service.parse_months(request.args.get("months"))))
    response.headers["Cache-Control"] = "private, no-store"
    return response


# ---- reports -----------------------------------------------------------------
HTML_ROWS = 200
REPORT_ARGS = ("from", "to", "day", "status")
MIMETYPES = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def _report_or_404(key):
    report = report_service.REPORTS.get(key)
    if report is None:
        abort(404)
    return report


@bp.route("/reports")
@role_required("admin")
def reports():
    return render_template("admin/reports.html", reports=list(report_service.REPORTS.values()))


@bp.route("/reports/<key>")
@role_required("admin")
def report_view(key):
    report = _report_or_404(key)
    params, errors = report_service.parse_params(report, request.args)
    data = report_service.run(report, params)
    today = utcnow().date()
    keep = {"status": params.status} if report.statuses and params.status != "all" else {}
    spans = [("Last 7 days", 7), ("Last 30 days", 30), ("Last 90 days", 90), ("Last 12 months", 365)]
    presets = [(label, url_for("admin.report_view", key=key, **{"from": (today - timedelta(days=d - 1)).isoformat(), "to": today.isoformat()}, **keep))
               for label, d in spans]
    presets.append(("All time", url_for("admin.report_view", key=key, **{"from": "2000-01-01", "to": today.isoformat()}, **keep)))
    return render_template(
        "admin/report.html", report=report, data=data, params=params, errors=errors, fmt=report_export.fmt,
        shown=data.rows[:HTML_ROWS], html_rows=HTML_ROWS, description=report_export.describe_params(report, params),
        qs={k: request.args[k] for k in REPORT_ARGS if request.args.get(k)}, presets=presets, status_choices=report_service.STATUS_CHOICES,
        from_value=params.start.date().isoformat() if params.start else "", to_value=params.last_day.isoformat() if params.end else "",
        day_value=params.day.isoformat() if params.day else "")


@bp.route("/reports/<key>/export/<any(pdf,xlsx):ext>")
@role_required("admin")
def report_export_file(key, ext):
    """Download a report as PDF or Excel with the same filters as the page (bad filters fall back to safe defaults)."""
    report = _report_or_404(key)
    params, _ = report_service.parse_params(report, request.args)
    data = report_service.run(report, params)
    now = utcnow()
    render = report_export.render_pdf if ext == "pdf" else report_export.render_xlsx
    return Response(render(report, data, params, now), mimetype=MIMETYPES[ext],
                    headers={"Content-Disposition": f'attachment; filename="{report_export.filename(report, ext, now)}"',
                             "Cache-Control": "private, no-store"})
