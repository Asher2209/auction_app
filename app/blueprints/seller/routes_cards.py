"""
Trading card creation and management routes
Handles seller workflow for collectible cards
"""

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from decimal import Decimal

from ...extensions import db
from ...models import (
    Category, Product, ProductImage, ProductDetails, CollectibleCard, CardType, CardImage,
    CollectibleVerification, utcnow
)
from ...services import auction_validation_service, card_auction_service, uploads
from ...services.card_identity_service import assign_platform_card_id
from ...services.qrcode_service import save_qr_code_to_file
from ...utils import role_required
from . import bp
from .forms_card_auction import CardAuctionForm
from .forms_cards import CollectibleCardForm

CARD_CATEGORY_NAME = "Trading Cards"


def _card_category():
    category = Category.query.filter_by(name=CARD_CATEGORY_NAME).first()
    if category is None:
        category = Category(name=CARD_CATEGORY_NAME)
        db.session.add(category)
        db.session.flush()
    return category


@bp.route("/collectibles", methods=["GET"])
@role_required("seller")
def collectibles_dashboard():
    """My Collectibles dashboard - seller's trading card inventory"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')
    sort = request.args.get('sort', 'newest')

    query = CollectibleCard.query.join(Product).filter(Product.seller_id == current_user.id)

    if status != 'all':
        if status == 'pending':
            query = query.join(CollectibleVerification).filter(
                CollectibleVerification.verification_status.in_(('pending', 'under_review'))
            )
        elif status == 'verified':
            query = query.join(CollectibleVerification).filter(
                CollectibleVerification.verification_status == 'verified'
            )
        elif status == 'rejected':
            query = query.join(CollectibleVerification).filter(
                CollectibleVerification.verification_status == 'rejected'
            )
        elif status == 'more_info':
            query = query.join(CollectibleVerification).filter(
                CollectibleVerification.verification_status == 'more_info_needed'
            )

    if sort == 'oldest':
        query = query.order_by(CollectibleCard.created_at.asc())
    elif sort == 'name':
        query = query.order_by(CollectibleCard.card_name.asc())
    else:
        query = query.order_by(CollectibleCard.created_at.desc())

    cards = query.paginate(page=page, per_page=12)

    return render_template(
        'seller/collectibles/dashboard.html',
        cards=cards,
        status=status,
        sort=sort
    )


@bp.route("/cards/new", methods=["GET", "POST"])
@role_required("seller")
def create_card():
    """Create a new collectible trading card listing"""
    form = CollectibleCardForm()

    if form.validate_on_submit():
        # Validate and save images
        files = [f for f in form.card_images.data if f and f.filename]
        error = None

        if not files:
            error = "Upload at least one card image."
        elif len(files) > 10:  # Cards can have more images (front, back, slab, etc.)
            error = "You can upload at most 10 images."

        saved = []
        if error is None:
            try:
                saved = uploads.save_images(files)
            except uploads.UploadError as e:
                error = str(e)

        if error:
            form.card_images.errors.append(error)
        else:
            try:
                # Create Product entry
                product = Product(
                    seller_id=current_user.id,
                    category_id=_card_category().id,
                    title=form.card_name.data.strip(),
                    description=form.condition_notes.data or "See card details for condition information.",
                    starting_price=form.estimated_value.data or Decimal("1.00"),
                    auction_start=utcnow(),
                    auction_end=utcnow(),  # Will be set by seller in next step
                    approval_status="pending",
                    images=[ProductImage(path=p) for p in saved],
                )
                db.session.add(product)
                db.session.commit()

                # Create CollectibleCard entry
                card_type = CardType.query.get(form.card_type_id.data)
                collectible_card = CollectibleCard(
                    product_id=product.id,
                    card_type_id=form.card_type_id.data,
                    card_name=form.card_name.data.strip(),
                    manufacturer=form.manufacturer.data,
                    set_name=form.set_name.data,
                    set_code=form.set_code.data,
                    release_year=form.release_year.data,
                    card_number=form.card_number.data,
                    rarity=form.rarity.data,
                    condition=form.condition.data,
                    condition_notes=form.condition_notes.data,
                    language=form.language.data or "English",
                    country=form.country.data,
                    edition=form.edition.data,
                    is_graded=form.is_graded.data,
                    grading_company=form.grading_company.data,
                    grade=form.grade.data,
                    certification_number=form.certification_number.data,
                    certification_url=form.certification_url.data,
                    estimated_value=form.estimated_value.data,
                )

                # Store type-specific details as JSON
                type_details = {}

                if card_type.slug == 'pokemon':
                    type_details = {
                        'pokemon_name': form.pokemon_name.data,
                        'hp': form.pokemon_hp.data,
                        'holo_type': form.pokemon_holo_type.data,
                        'first_edition': form.pokemon_first_edition.data,
                        'shadowless': form.pokemon_shadowless.data,
                        'promo': form.pokemon_promo.data,
                        'illustrator': form.pokemon_illustrator.data,
                    }
                elif card_type.slug == 'football':
                    type_details = {
                        'player_name': form.football_player_name.data,
                        'team': form.football_team.data,
                        'national_team': form.football_national_team.data,
                        'league': form.football_league.data,
                        'season': form.football_season.data,
                        'is_rookie': form.football_is_rookie.data,
                        'is_autograph': form.football_is_autograph.data,
                        'is_relic': form.football_is_relic.data,
                        'is_numbered': form.football_is_numbered.data,
                        'serial_number': form.football_serial_number.data,
                    }

                if type_details:
                    collectible_card.set_type_details(type_details)

                db.session.add(collectible_card)
                db.session.commit()

                # PHASE 1: Assign unique Platform Card ID (CARD-XXXXXX format)
                platform_card_id = assign_platform_card_id(collectible_card)

                # Save card images with type information
                for i, saved_path in enumerate(saved):
                    # Infer image type from order: first=front, second=back, rest=detail/slab
                    image_type = 'front' if i == 0 else ('back' if i == 1 else 'detail')
                    card_image = CardImage(
                        collectible_card_id=collectible_card.id,
                        image_type=image_type,
                        path=saved_path
                    )
                    db.session.add(card_image)

                # PHASE 1: Generate QR code pointing to public verification page
                try:
                    qr_code_path = save_qr_code_to_file(platform_card_id, collectible_card.id)
                    current_app.logger.info(f"QR code generated for {platform_card_id} at {qr_code_path}")
                except Exception as qr_error:
                    current_app.logger.warning(f"QR code generation failed for {platform_card_id}: {str(qr_error)}")
                    # Continue even if QR code fails, it's not critical

                # Create verification entry (ungraded cards pending manual review)
                verification = CollectibleVerification(
                    product_id=product.id,
                    collectible_card_id=collectible_card.id,
                    collectible_type='trading_card',
                    is_graded=collectible_card.is_graded,
                    verification_status='pending',
                    submission_count=1,
                )
                db.session.add(verification)
                db.session.commit()

                flash(
                    f"Card '{collectible_card.card_name}' created successfully! "
                    f"Platform ID: <strong>{platform_card_id}</strong>. "
                    "It's awaiting verification. You'll be able to create an auction once approved.",
                    "success"
                )
                return redirect(url_for('seller.product_detail', product_id=product.id))

            except Exception as e:
                db.session.rollback()
                uploads.delete_files(saved)
                flash(f"Error creating card listing: {str(e)}", "danger")

    return render_template("seller/cards/card_form.html", form=form, card_types=CardType.query.filter_by(is_active=True))


@bp.route("/cards/<int:card_id>", methods=["GET"])
@role_required("seller")
def view_card(card_id):
    """View collectible card details"""
    from ...models import CollectibleCard

    card = CollectibleCard.query.get_or_404(card_id)

    # Verify ownership
    if card.product.seller_id != current_user.id:
        abort(403)

    verification = card.product.collectible_verification
    card_images = card.images
    type_details = card.get_type_details()

    return render_template(
        "seller/cards/card_detail.html",
        card=card,
        product=card.product,
        verification=verification,
        card_images=card_images,
        type_details=type_details,
        auction=card.product.auction,
        listing=auction_validation_service.check_listing(card.product),
    )


@bp.route("/cards/<int:card_id>/auction", methods=["GET", "POST"])
@role_required("seller")
def create_card_auction(card_id):
    """Put a verified, token-backed card up for auction. Every rule is enforced by the service, not by this page."""
    card = db.session.get(CollectibleCard, card_id)
    if card is None or card.product.seller_id != current_user.id:
        abort(404)  # 404 so sellers cannot probe for other sellers' cards
    product = card.product
    if product.auction is not None:
        flash("This card already has an auction.", "info")
        return redirect(url_for("seller.view_card", card_id=card.id))

    form = CardAuctionForm()
    status = 200
    if form.validate_on_submit():
        try:
            auction = card_auction_service.create_card_auction(
                product, current_user, form.starting_bid.data, form.start_time.data, form.duration_hours.data)
        except card_auction_service.CardAuctionError as e:
            flash(e.message, "danger")
            status = e.status
        else:
            flash("Your auction has been created.", "success")
            return redirect(url_for("auctions.detail", auction_id=auction.id))
    return render_template("seller/cards/card_auction.html", form=form, card=card, product=product,
                           listing=auction_validation_service.check_listing(product)), status


@bp.route("/cards/<int:card_id>/edit", methods=["GET", "POST"])
@role_required("seller")
def edit_card(card_id):
    """Edit collectible card details (only before verification)"""
    from ...models import CollectibleCard

    card = CollectibleCard.query.get_or_404(card_id)

    # Verify ownership
    if card.product.seller_id != current_user.id:
        abort(403)

    # Prevent editing if verified or auction active
    verification = card.product.collectible_verification
    if verification and verification.verification_status == 'verified':
        flash("You cannot edit a verified card listing.", "warning")
        return redirect(url_for('seller.view_card', card_id=card_id))

    if card.product.auction and card.product.auction.status in ('active', 'closed'):
        flash("You cannot edit a card once the auction has started.", "warning")
        return redirect(url_for('seller.view_card', card_id=card_id))

    form = CollectibleCardForm()

    if form.validate_on_submit():
        # Update card information
        card.card_name = form.card_name.data.strip()
        card.manufacturer = form.manufacturer.data
        card.set_name = form.set_name.data
        card.set_code = form.set_code.data
        card.release_year = form.release_year.data
        card.card_number = form.card_number.data
        card.rarity = form.rarity.data
        card.condition = form.condition.data
        card.condition_notes = form.condition_notes.data
        card.language = form.language.data or "English"
        card.country = form.country.data
        card.edition = form.edition.data
        card.is_graded = form.is_graded.data
        card.grading_company = form.grading_company.data
        card.grade = form.grade.data
        card.certification_number = form.certification_number.data
        card.certification_url = form.certification_url.data
        card.estimated_value = form.estimated_value.data

        # Update product title and description
        card.product.title = form.card_name.data.strip()
        card.product.description = form.condition_notes.data or "See card details for condition information."
        card.product.starting_price = form.estimated_value.data or Decimal("1.00")
        card.product.approval_status = "pending"  # Reset to pending for re-verification

        # Reset verification on edit
        if verification:
            verification.verification_status = "pending"
            verification.submission_count += 1

        db.session.commit()
        flash("Card listing updated and resubmitted for verification.", "success")
        return redirect(url_for('seller.view_card', card_id=card_id))

    elif request.method == "GET":
        # Pre-fill form with existing data
        form.card_type_id.data = card.card_type_id
        form.card_name.data = card.card_name
        form.manufacturer.data = card.manufacturer
        form.set_name.data = card.set_name
        form.set_code.data = card.set_code
        form.release_year.data = card.release_year
        form.card_number.data = card.card_number
        form.rarity.data = card.rarity
        form.condition.data = card.condition
        form.condition_notes.data = card.condition_notes
        form.language.data = card.language
        form.country.data = card.country
        form.edition.data = card.edition
        form.is_graded.data = card.is_graded
        form.grading_company.data = card.grading_company
        form.grade.data = card.grade
        form.certification_number.data = card.certification_number
        form.certification_url.data = card.certification_url
        form.estimated_value.data = card.estimated_value

        # Pre-fill type-specific fields
        type_details = card.get_type_details()
        if card.card_type.slug == 'pokemon':
            form.pokemon_name.data = type_details.get('pokemon_name')
            form.pokemon_hp.data = type_details.get('hp')
            form.pokemon_holo_type.data = type_details.get('holo_type')
            form.pokemon_first_edition.data = type_details.get('first_edition', False)
            form.pokemon_shadowless.data = type_details.get('shadowless', False)
            form.pokemon_promo.data = type_details.get('promo', False)
            form.pokemon_illustrator.data = type_details.get('illustrator')
        elif card.card_type.slug == 'football':
            form.football_player_name.data = type_details.get('player_name')
            form.football_team.data = type_details.get('team')
            form.football_national_team.data = type_details.get('national_team')
            form.football_league.data = type_details.get('league')
            form.football_season.data = type_details.get('season')
            form.football_is_rookie.data = type_details.get('is_rookie', False)
            form.football_is_autograph.data = type_details.get('is_autograph', False)
            form.football_is_relic.data = type_details.get('is_relic', False)
            form.football_is_numbered.data = type_details.get('is_numbered', False)
            form.football_serial_number.data = type_details.get('serial_number')

    return render_template(
        "seller/cards/card_form.html",
        form=form,
        card=card,
        card_types=CardType.query.filter_by(is_active=True)
    )


@bp.route("/cards/debug")
def debug_template():
    """Debug route to check template content"""
    import os
    template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'templates', 'seller', 'cards', 'card_form.html')
    
    if os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return f"Template found at: {template_path}<br>Size: {len(content)} bytes<br>Contains 'DIRECT HTML': {'DIRECT HTML' in content}"
    else:
        return f"Template NOT found at: {template_path}"
