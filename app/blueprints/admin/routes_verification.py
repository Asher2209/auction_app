"""
Admin routes for collectible card verification workflow
"""

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func
from datetime import timedelta

from ...extensions import db
from ...models import (
    CollectibleVerification, CollectibleCard, CardVerificationChecklist,
    CardVerificationHistory, Product, User, utcnow, BlockchainAsset
)
from ...services import auction_validation_service, card_identity_service, qrcode_service
from ...services.verification_completion_service import complete_verification_and_create_blockchain_asset
from ...utils import role_required
from . import bp
from .forms_verification import (
    CardVerificationChecklistForm, CardApprovalForm, CardRejectionForm,
    CardMoreInfoForm
)


@bp.route("/cards/verify", methods=["GET"])
@role_required("admin")
def cards_verify_dashboard():
    """Main card verification dashboard"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status')
    card_type = request.args.get('card_type')
    sort = request.args.get('sort', 'newest')

    # Base query
    query = CollectibleVerification.query.filter_by(is_graded=False).join(CollectibleCard).join(Product)

    # Filter by status
    if status and status in ('pending', 'under_review', 'more_info_needed', 'verified', 'rejected'):
        query = query.filter(CollectibleVerification.verification_status == status)
    else:
        # Show pending and under review by default
        query = query.filter(CollectibleVerification.verification_status.in_(('pending', 'under_review')))

    # Filter by card type
    if card_type:
        query = query.filter(CollectibleCard.card_type_id == card_type)

    # Sort
    if sort == 'oldest':
        query = query.order_by(CollectibleVerification.created_at.asc())
    elif sort == 'high_value':
        query = query.order_by(CollectibleCard.estimated_value.desc())
    else:  # newest
        query = query.order_by(CollectibleVerification.created_at.desc())

    # Paginate
    verifications = query.paginate(page=page, per_page=20)

    # Calculate stats
    all_verifications = CollectibleVerification.query.filter_by(is_graded=False)
    pending_count = all_verifications.filter(CollectibleVerification.verification_status.in_(('pending', 'under_review'))).count()
    verified_count = all_verifications.filter(CollectibleVerification.verification_status == 'verified').count()
    rejected_count = all_verifications.filter(CollectibleVerification.verification_status == 'rejected').count()
    info_needed_count = all_verifications.filter(CollectibleVerification.verification_status == 'more_info_needed').count()

    # Average verification time
    reviewed = all_verifications.filter(CollectibleVerification.verification_date.isnot(None)).all()
    avg_review_time = 0
    if reviewed:
        total_time = sum((v.verification_date - v.created_at).total_seconds() for v in reviewed if v.verification_date)
        avg_review_time = int(total_time / len(reviewed) / 3600)  # Convert to hours

    return render_template(
        'admin/cards_verification_dashboard.html',
        verifications=verifications,
        pending_count=pending_count,
        verified_count=verified_count,
        rejected_count=rejected_count,
        info_needed_count=info_needed_count,
        avg_review_time=avg_review_time,
        status=status,
        card_type=card_type,
        sort=sort
    )


@bp.route("/cards/verify/<int:verification_id>", methods=["GET"])
@role_required("admin")
def card_verification_detail(verification_id):
    """View detailed verification page for a card"""
    verification = CollectibleVerification.query.get_or_404(verification_id)

    if verification.is_graded:
        abort(403)  # This is for graded cards verification, use different route

    card = verification.collectible_card
    product = verification.product
    seller = product.seller
    card_images = card.images
    type_details = card.get_type_details()

    # Get existing checklist
    checklist_items = CardVerificationChecklist.query.filter_by(verification_id=verification_id).all()
    checklist_dict = {item.check_type: item for item in checklist_items}

    # Get history
    history = CardVerificationHistory.query.filter_by(verification_id=verification_id).order_by(
        CardVerificationHistory.created_at.desc()
    ).all()

    # Initialize forms
    form = CardVerificationChecklistForm()
    approval_form = CardApprovalForm()
    rejection_form = CardRejectionForm()
    info_form = CardMoreInfoForm()

    return render_template(
        'admin/card_verification_detail.html',
        verification=verification,
        card=card,
        product=product,
        seller=seller,
        card_images=card_images,
        type_details=type_details,
        checklist_dict=checklist_dict,
        history=history,
        form=form,
        approval_form=approval_form,
        rejection_form=rejection_form,
        info_form=info_form
    )


@bp.route("/cards/verify/<int:verification_id>/checklist", methods=["POST"])
@role_required("admin")
def save_verification_checklist(verification_id):
    """Save verification checklist"""
    verification = CollectibleVerification.query.get_or_404(verification_id)
    form = CardVerificationChecklistForm()

    if form.validate_on_submit():
        # Delete existing checklist items
        CardVerificationChecklist.query.filter_by(verification_id=verification_id).delete()

        # Create new checklist items
        checks = [
            ('card_identity', form.card_identity_result.data, form.card_identity_notes.data),
            ('set_checked', form.set_checked_result.data, form.set_checked_notes.data),
            ('card_number', form.card_number_result.data, form.card_number_notes.data),
            ('manufacturer', form.manufacturer_result.data, form.manufacturer_notes.data),
            ('images_reviewed', form.images_reviewed_result.data, form.images_reviewed_notes.data),
            ('condition_reviewed', form.condition_reviewed_result.data, form.condition_reviewed_notes.data),
            ('grading_checked', form.grading_checked_result.data, form.grading_checked_notes.data),
            ('seller_info_reviewed', form.seller_info_reviewed_result.data, form.seller_info_reviewed_notes.data),
            ('counterfeit_check', form.counterfeit_check_result.data, form.counterfeit_check_notes.data),
        ]

        for check_type, result, notes in checks:
            if result:
                item = CardVerificationChecklist(
                    verification_id=verification_id,
                    check_type=check_type,
                    result=result,
                    notes=notes
                )
                db.session.add(item)

        # Update overall notes
        verification.admin_notes = form.overall_notes.data
        verification.verification_status = 'under_review'

        db.session.commit()
        flash('Verification checklist saved.', 'success')
    else:
        flash('Error saving checklist.', 'danger')

    return redirect(url_for('admin.card_verification_detail', verification_id=verification_id))


@bp.route("/cards/verify/<int:verification_id>/approve", methods=["POST"])
@role_required("admin")
def approve_card(verification_id):
    """Approve a card for auction"""
    verification = CollectibleVerification.query.get_or_404(verification_id)
    form = CardApprovalForm()

    if form.validate_on_submit():
        # Create history entry
        history = CardVerificationHistory(
            verification_id=verification_id,
            previous_status=verification.verification_status,
            new_status='verified',
            changed_by=current_user.id,
            change_reason=form.approval_notes.data
        )
        db.session.add(history)

        # Update verification
        verification.verification_status = 'verified'
        verification.verification_date = utcnow()
        verification.verified_by = current_user.id
        verification.admin_notes = form.approval_notes.data

        # Update product status
        verification.product.approval_status = 'approved'

        db.session.commit()

        flash(f"Card '{verification.collectible_card.card_name}' approved! âœ“", 'success')

        for warning in auction_validation_service.find_duplicate_signals(verification.collectible_card).warnings:
            flash(warning.message, 'warning')
        result = complete_verification_and_create_blockchain_asset(verification, verification.product.seller.wallet_address)
        flash(result['message'], 'info' if result['success'] else 'warning')
    else:
        flash('Error approving card.', 'danger')

    return redirect(url_for('admin.card_verification_detail', verification_id=verification_id))


@bp.route("/cards/verify/<int:verification_id>/reject", methods=["POST"])
@role_required("admin")
def reject_card(verification_id):
    """Reject a card listing"""
    verification = CollectibleVerification.query.get_or_404(verification_id)
    form = CardRejectionForm()

    if form.validate_on_submit():
        # Create history entry
        history = CardVerificationHistory(
            verification_id=verification_id,
            previous_status=verification.verification_status,
            new_status='rejected',
            changed_by=current_user.id,
            change_reason=form.rejection_details.data
        )
        db.session.add(history)

        # Update verification
        verification.verification_status = 'rejected'
        verification.verification_date = utcnow()
        verification.verified_by = current_user.id
        verification.rejection_reason = form.rejection_reason.data
        verification.admin_notes = form.rejection_details.data

        # Update product status
        verification.product.approval_status = 'rejected'
        verification.product.rejection_reason = form.rejection_details.data

        db.session.commit()

        flash(f"Card '{verification.collectible_card.card_name}' rejected.", 'warning')
    else:
        flash('Error rejecting card.', 'danger')

    return redirect(url_for('admin.cards_verify_dashboard'))


@bp.route("/cards/verify/<int:verification_id>/more-info", methods=["POST"])
@role_required("admin")
def request_card_info(verification_id):
    """Request more information from seller"""
    verification = CollectibleVerification.query.get_or_404(verification_id)
    form = CardMoreInfoForm()

    if form.validate_on_submit():
        # Create history entry
        history = CardVerificationHistory(
            verification_id=verification_id,
            previous_status=verification.verification_status,
            new_status='more_info_needed',
            changed_by=current_user.id,
            change_reason=form.message.data
        )
        db.session.add(history)

        # Update verification
        verification.verification_status = 'more_info_needed'
        verification.admin_notes = f"{form.info_request.data}: {form.message.data}"

        db.session.commit()

        flash(f"Seller notified to provide more information.", 'info')
    else:
        flash('Error sending request.', 'danger')

    return redirect(url_for('admin.card_verification_detail', verification_id=verification_id))


