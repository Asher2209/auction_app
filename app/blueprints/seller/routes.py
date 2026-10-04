from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ...extensions import db
from ...models import Auction, Category, Product, ProductImage, Review
from ...services import review_service as rs
from ...services import uploads
from ...utils import role_required
from . import bp
from .forms import DT_FORMAT, ProductForm

TABS = ("all", "pending", "active", "completed")


def _own_product_or_404(product_id):
    # 404 (not 403) so sellers cannot probe for other sellers' product ids
    product = db.session.get(Product, product_id)
    if product is None or product.seller_id != current_user.id:
        abort(404)
    return product


def _set_categories(form):
    form.category_id.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name)]


@bp.route("/")
@role_required("seller")
def dashboard():
    tab = request.args.get("tab", "all")
    if tab not in TABS:
        tab = "all"
    q = Product.query.filter_by(seller_id=current_user.id).outerjoin(Auction)
    if tab == "pending":
        q = q.filter(Product.approval_status.in_(("pending", "rejected")))
    elif tab == "active":
        q = q.filter(Auction.status.in_(("scheduled", "active")))
    elif tab == "completed":
        q = q.filter(Auction.status == "closed")
    products = q.order_by(Product.created_at.desc()).all()
    return render_template("seller/dashboard.html", products=products, tab=tab, tabs=TABS)


@bp.route("/products/new", methods=["GET", "POST"])
@role_required("seller")
def create_product():
    form = ProductForm()
    _set_categories(form)
    if form.validate_on_submit():
        files = [f for f in form.images.data if f and f.filename]
        error = None
        if not files:
            error = "Upload at least one product image."
        elif len(files) > current_app.config["MAX_IMAGES_PER_PRODUCT"]:
            error = f"You can upload at most {current_app.config['MAX_IMAGES_PER_PRODUCT']} images."
        saved = []
        if error is None:
            try:
                saved = uploads.save_images(files)
            except uploads.UploadError as e:
                error = str(e)
        if error:
            form.images.errors.append(error)
        else:
            product = Product(
                seller_id=current_user.id,
                category_id=form.category_id.data,
                title=form.title.data.strip(),
                description=form.description.data.strip(),
                starting_price=form.starting_price.data,
                auction_start=form.auction_start.data,
                auction_end=form.auction_end.data,
                approval_status="pending",
                images=[ProductImage(path=p) for p in saved],
            )
            try:
                db.session.add(product)
                db.session.commit()
            except Exception:
                db.session.rollback()
                uploads.delete_files(saved)
                raise
            flash("Product submitted. It will go live once an administrator approves it.", "success")
            return redirect(url_for("seller.product_detail", product_id=product.id))
    return render_template("seller/product_form.html", form=form, product=None)


@bp.route("/products/<int:product_id>")
@role_required("seller")
def product_detail(product_id):
    product = _own_product_or_404(product_id)
    auction = product.auction
    bids = auction.bids[:10] if auction else []
    return render_template("seller/product_detail.html", product=product, auction=auction, bids=bids,
                           reviews=rs.visible_reviews(product.id),
                           stats=rs.stats_for_products([product.id]).get(product.id))


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@role_required("seller")
def edit_product(product_id):
    product = _own_product_or_404(product_id)
    if not product.is_editable:
        flash("This auction has already started, so the product can no longer be edited.", "warning")
        return redirect(url_for("seller.product_detail", product_id=product.id))

    form = ProductForm(obj=product)
    _set_categories(form)
    if request.method == "GET":
        form.auction_start.data = product.auction_start
        form.auction_end.data = product.auction_end

    if form.validate_on_submit():
        max_images = current_app.config["MAX_IMAGES_PER_PRODUCT"]
        remove_ids = {int(i) for i in request.form.getlist("remove_image") if i.isdigit()}
        to_remove = [img for img in product.images if img.id in remove_ids]  # only this product's images
        keep = len(product.images) - len(to_remove)
        files = [f for f in form.images.data if f and f.filename]

        error = None
        if keep + len(files) < 1:
            error = "A product needs at least one image."
        elif keep + len(files) > max_images:
            error = f"A product can have at most {max_images} images."
        saved = []
        if error is None:
            try:
                saved = uploads.save_images(files)
            except uploads.UploadError as e:
                error = str(e)
        if error:
            form.images.errors.append(error)
        else:
            product.title = form.title.data.strip()
            product.category_id = form.category_id.data
            product.description = form.description.data.strip()
            product.starting_price = form.starting_price.data
            product.auction_start = form.auction_start.data
            product.auction_end = form.auction_end.data
            # Any change sends the listing back for admin review; drop its scheduled auction.
            product.approval_status = "pending"
            product.rejection_reason = None
            if product.auction is not None:
                db.session.delete(product.auction)
            removed_paths = [img.path for img in to_remove]
            for img in to_remove:
                product.images.remove(img)
            product.images.extend(ProductImage(path=p) for p in saved)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                uploads.delete_files(saved)
                raise
            uploads.delete_files(removed_paths)
            flash("Product updated and resubmitted for approval.", "success")
            return redirect(url_for("seller.product_detail", product_id=product.id))

    return render_template("seller/product_form.html", form=form, product=product, dt_format=DT_FORMAT)


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@role_required("seller")
def delete_product(product_id):
    product = _own_product_or_404(product_id)
    if not product.is_editable:
        flash("This auction has already started, so the product can no longer be deleted.", "warning")
        return redirect(url_for("seller.product_detail", product_id=product.id))
    paths = [img.path for img in product.images]
    if product.auction is not None:
        db.session.delete(product.auction)
    db.session.delete(product)
    db.session.commit()
    uploads.delete_files(paths)
    flash("Product deleted.", "info")
    return redirect(url_for("seller.dashboard"))


@bp.route("/reviews")
@role_required("seller")
def reviews():
    """Visible reviews on this seller's products (moderator-hidden ones are not shown)."""
    rows = (Review.query.join(Product, Review.product_id == Product.id)
            .filter(Product.seller_id == current_user.id, Review.is_hidden.is_(False))
            .order_by(Review.created_at.desc(), Review.id.desc()).all())
    return render_template("seller/reviews.html", reviews=rows, overall=rs.seller_stats(current_user.id))
