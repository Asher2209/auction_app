from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from ...extensions import db
from ...models import Product, Review
from ...services import review_service as rs
from ...services import uploads
from ...utils import role_required
from . import bp

TABS = ("all", "pending", "active", "completed")


def _own_product_or_404(product_id):
    # 404 (not 403) so sellers cannot probe for other sellers' product ids
    product = db.session.get(Product, product_id)
    if product is None or product.seller_id != current_user.id:
        abort(404)
    return product


@bp.route("/")
@role_required("seller")
def dashboard():
    # Redirect to collectibles dashboard (dedicated cards interface)
    return redirect(url_for("seller.collectibles_dashboard"))

@bp.route("/products/new")
@role_required("seller")
def create_product():
    # ChainBid lists trading cards only; the old generic product form is gone.
    return redirect(url_for("seller.create_card"))


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
    if product.collectible_card is not None:
        flash("Trading cards are managed from My Collectibles, not from this page.", "warning")
        return redirect(url_for("seller.view_card", card_id=product.collectible_card.id))
    # A listing without a card record predates the cards-only site and can no longer be edited.
    flash("Only trading cards can be listed now, so this listing can no longer be edited. "
          "Delete it if it has not started, and list the card from My Collectibles.", "warning")
    return redirect(url_for("seller.product_detail", product_id=product.id))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@role_required("seller")
def delete_product(product_id):
    product = _own_product_or_404(product_id)
    if product.collectible_card is not None:
        flash("Trading cards are managed from My Collectibles, not from this page.", "warning")
        return redirect(url_for("seller.view_card", card_id=product.collectible_card.id))
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
