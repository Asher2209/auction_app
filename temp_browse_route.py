@bp.route("/browse", methods=["GET"])
def browse():
    """Unified browse for auctions and trading cards"""
    from sqlalchemy import or_
    
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
