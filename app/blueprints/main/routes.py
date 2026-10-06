from datetime import timedelta

from flask import flash, redirect, render_template, url_for, request, abort, jsonify
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import TextAreaField
from wtforms.validators import DataRequired, Length

from ...extensions import db
from ...models import Auction, Category, Feedback, utcnow, CollectibleCard, CardType, Product
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


@bp.route("/cards/search", methods=["GET"])
def search_cards():
    """Search and filter collectible cards"""
    from sqlalchemy import or_, and_
    
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    card_type = request.args.get('type')
    condition = request.args.get('condition')
    graded = request.args.get('graded')
    grader = request.args.get('grader')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    sort = request.args.get('sort', 'newest')
    
    query = CollectibleCard.query.filter(
        CollectibleCard.product.has(approval_status='approved')
    )
    
    if q:
        search_term = f"%{q}%"
        query = query.filter(
            or_(
                CollectibleCard.card_name.ilike(search_term),
                CollectibleCard.set_name.ilike(search_term),
                CollectibleCard.manufacturer.ilike(search_term),
            )
        )
    
    if card_type:
        try:
            card_type_id = int(card_type)
            query = query.filter(CollectibleCard.card_type_id == card_type_id)
        except (ValueError, TypeError):
            pass
    
    conditions_list = ['Poor', 'Fair', 'Good', 'Very Good', 'Excellent', 'Near Mint', 'Mint']
    if condition and condition in conditions_list:
        query = query.filter(CollectibleCard.condition == condition)
    
    if graded == 'true':
        query = query.filter(CollectibleCard.is_graded == True)
    elif graded == 'false':
        query = query.filter(CollectibleCard.is_graded == False)
    
    graders_list = ['PSA', 'Beckett', 'CGC']
    if grader and grader in graders_list:
        query = query.filter(CollectibleCard.grading_company == grader)
    
    if min_price is not None:
        query = query.filter(CollectibleCard.estimated_value >= min_price)
    if max_price is not None:
        query = query.filter(CollectibleCard.estimated_value <= max_price)
    
    if sort == 'price_low':
        query = query.order_by(CollectibleCard.estimated_value.asc())
    elif sort == 'price_high':
        query = query.order_by(CollectibleCard.estimated_value.desc())
    elif sort == 'rarity':
        query = query.order_by(CollectibleCard.rarity.desc())
    elif sort == 'oldest':
        query = query.order_by(CollectibleCard.created_at.asc())
    else:
        query = query.order_by(CollectibleCard.created_at.desc())
    
    cards = query.paginate(page=page, per_page=12)
    card_types = CardType.query.order_by(CardType.name).all()
    
    return render_template(
        'cards/search_results.html',
        cards=cards,
        q=q,
        card_type=card_type,
        condition=condition,
        graded=graded,
        grader=grader,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        card_types=card_types,
        conditions=conditions_list,
        graders=graders_list
    )



@bp.route("/shop", methods=["GET"])
def shop():
    """Unified browse for auctions and trading cards"""
    page = request.args.get('page', 1, type=int)
    category_filter = request.args.get('category', 'all')
    sort = request.args.get('sort', 'newest')
    card_type_slug = request.args.get('card_type')
    
    items = []
    all_card_types = CardType.query.order_by(CardType.name).all()
    card_type = None
    if card_type_slug:
        card_type = CardType.query.filter_by(slug=card_type_slug).first()
    
    if category_filter in ('all', 'auctions'):
        auction_query = Auction.query.filter(
            Auction.status.in_(['scheduled', 'active'])
        )
        if sort == 'price_low':
            auction_query = auction_query.order_by(Auction.current_bid.asc())
        elif sort == 'price_high':
            auction_query = auction_query.order_by(Auction.current_bid.desc())
        else:
            auction_query = auction_query.order_by(Auction.start_time.desc())
        auctions = auction_query.limit(12).all()
        items.extend([{'type': 'auction', 'data': a} for a in auctions])
    
    if category_filter in ('all', 'cards'):
        card_query = CollectibleCard.query.filter(
            CollectibleCard.product.has(approval_status='approved')
        )
        if card_type:
            card_query = card_query.filter(CollectibleCard.card_type_id == card_type.id)
        if sort == 'price_low':
            card_query = card_query.order_by(CollectibleCard.estimated_value.asc())
        elif sort == 'price_high':
            card_query = card_query.order_by(CollectibleCard.estimated_value.desc())
        else:
            card_query = card_query.order_by(CollectibleCard.created_at.desc())
        cards = card_query.limit(12).all()
        items.extend([{'type': 'card', 'data': c} for c in cards])
    
    per_page = 12
    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = items[start:end]
    total = len(items)
    
    return render_template(
        'browse.html',
        items=paginated_items,
        category=category_filter,
        card_type=card_type,
        all_card_types=all_card_types,
        sort=sort,
        page=page,
        total=total,
        per_page=per_page,
        has_next=end < total,
        has_prev=page > 1
    )

@bp.route("/cards/browse", methods=["GET"])
def browse_cards():
    """Browse cards by type"""
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'newest')
    card_type_slug = request.args.get('type')
    
    card_type = None
    if card_type_slug:
        card_type = CardType.query.filter_by(slug=card_type_slug).first()
        if not card_type:
            abort(404)
    
    query = CollectibleCard.query.filter(
        CollectibleCard.product.has(approval_status='approved')
    )
    
    if card_type:
        query = query.filter(CollectibleCard.card_type_id == card_type.id)
    
    if sort == 'price_low':
        query = query.order_by(CollectibleCard.estimated_value.asc())
    elif sort == 'price_high':
        query = query.order_by(CollectibleCard.estimated_value.desc())
    else:
        query = query.order_by(CollectibleCard.created_at.desc())
    
    cards = query.paginate(page=page, per_page=12)
    all_types = CardType.query.order_by(CardType.name).all()
    
    return render_template(
        'cards/browse.html',
        cards=cards,
        card_type=card_type,
        all_types=all_types,
        sort=sort
    )


@bp.route("/cards/<int:card_id>", methods=["GET"])
def view_card(card_id):
    """View a specific card listing"""
    from sqlalchemy import or_, and_
    
    card = CollectibleCard.query.get_or_404(card_id)
    product = card.product
    
    if product.approval_status != 'approved':
        abort(404)
    
    seller = product.seller
    images = card.images
    
    related = CollectibleCard.query.join(Product).filter(
        and_(
            CollectibleCard.card_type_id == card.card_type_id,
            CollectibleCard.id != card.id,
            Product.approval_status == 'approved'
        )
    ).limit(4).all()
    
    return render_template(
        'cards/view_card.html',
        card=card,
        product=product,
        seller=seller,
        images=images,
        related=related
    )


@bp.route("/api/cards/search", methods=["GET"])
def api_search_cards():
    """API endpoint for card search autocomplete"""
    q = request.args.get('q', '').strip()
    limit = request.args.get('limit', 10, type=int)
    
    if len(q) < 2:
        return jsonify([])
    
    query = CollectibleCard.query.filter(
        CollectibleCard.product.has(approval_status='approved')
    )
    
    search_term = f"%{q}%"
    results = query.filter(
        CollectibleCard.card_name.ilike(search_term)
    ).limit(limit).all()
    
    return jsonify([{
        'id': card.id,
        'name': card.card_name,
        'type': card.card_type.name,
        'set': card.set_name,
        'value': float(card.estimated_value) if card.estimated_value else 0
    } for card in results])

