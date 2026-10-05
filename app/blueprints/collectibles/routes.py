from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
import os
import json
from datetime import datetime

from . import bp
from ...models import Product, CollectibleVerification, VerificationLog, SupportedGrader
from ...services.collectible_verification_service import CollectibleVerificationService
from ...services import uploads
from ...extensions import db
from ...utils import role_required
from ..seller.forms_collectibles import CollectibleVerificationForm, CollectiblePhotoVerificationForm, CollectibleFilterForm


@bp.route('/product/<int:product_id>/verify', methods=['GET', 'POST'])
@login_required
@role_required('seller')
def verify_collectible(product_id):
    """Verify a collectible item with certificate number"""
    product = Product.query.get_or_404(product_id)

    # Check ownership
    if product.seller_id != current_user.id:
        abort(403)

    # Check if already verified
    existing = CollectibleVerification.query.filter_by(product_id=product_id).first()
    if existing and existing.verification_status == 'verified':
        flash('This item is already verified.', 'info')
        return redirect(url_for('seller.product_detail', product_id=product_id))

    form = CollectibleVerificationForm()
    if form.validate_on_submit():
        try:
            # Attempt verification
            result = CollectibleVerificationService.verify_certificate(
                product_id=product_id,
                collectible_type=form.collectible_type.data,
                grader=form.grader.data,
                certificate_number=form.certificate_number.data.strip(),
                grade=form.grade.data or None,
                year=form.year.data or None
            )

            # Get the verification record
            verification = CollectibleVerification.query.filter_by(product_id=product_id).first()
            if form.grader_item_name.data:
                verification.grader_item_name = form.grader_item_name.data
            if form.notes.data:
                verification.notes = form.notes.data

            # Save photos if uploaded
            if form.slab_photos.data:
                try:
                    photo_files = [f for f in form.slab_photos.data if f and f.filename]
                    if photo_files:
                        saved_paths = uploads.save_images(photo_files)
                        verification.slab_photo_urls = json.dumps(saved_paths)
                except Exception as e:
                    flash(f'Error uploading photos: {str(e)}', 'danger')

            db.session.commit()

            if result.get('status') == 'duplicate_detected':
                flash(
                    f"Certificate already registered. {result.get('message')}",
                    'warning'
                )
            elif verification.verification_status == 'verified':
                flash(
                    f'Certificate verified successfully! Your {form.collectible_type.data.replace("_", " ").title()} is now certified.',
                    'success'
                )
            else:
                flash(
                    'Certificate submitted for manual verification. A moderator will review your photos and certificate details.',
                    'info'
                )

            return redirect(url_for('seller.product_detail', product_id=product_id))

        except Exception as e:
            flash(f'Error during verification: {str(e)}', 'danger')

    return render_template('collectibles/verify.html', form=form, product=product, existing=existing)


@bp.route('/product/<int:product_id>/verify-photos', methods=['GET', 'POST'])
@login_required
@role_required('seller')
def upload_verification_photos(product_id):
    """Upload additional photos for manual verification"""
    product = Product.query.get_or_404(product_id)
    verification = CollectibleVerification.query.filter_by(product_id=product_id).first_or_404()

    # Check ownership
    if product.seller_id != current_user.id:
        abort(403)

    if verification.verification_status == 'verified':
        flash('This item is already verified.', 'info')
        return redirect(url_for('seller.product_detail', product_id=product_id))

    form = CollectiblePhotoVerificationForm()
    if form.validate_on_submit():
        try:
            photo_files = [f for f in form.slab_photos.data if f and f.filename]
            if photo_files:
                saved_paths = uploads.save_images(photo_files)
                verification.slab_photo_urls = json.dumps(saved_paths)
                if form.photo_notes.data:
                    verification.notes = form.photo_notes.data

                db.session.commit()

                # Log the photo upload
                log = VerificationLog(
                    collectible_id=verification.id,
                    action='photo_upload',
                    status='success',
                    details=json.dumps({'photo_count': len(saved_paths)}),
                    performed_by=current_user.email
                )
                db.session.add(log)
                db.session.commit()

                flash(f'Uploaded {len(saved_paths)} photo(s) for verification.', 'success')
                return redirect(url_for('seller.product_detail', product_id=product_id))
        except Exception as e:
            flash(f'Error uploading photos: {str(e)}', 'danger')

    return render_template('collectibles/upload_photos.html',
                          form=form, product=product, verification=verification)


@bp.route('/verify-status/<int:product_id>')
@login_required
def get_verification_status(product_id):
    """API endpoint to get verification status"""
    product = Product.query.get_or_404(product_id)
    verification = CollectibleVerification.query.filter_by(product_id=product_id).first()

    if not verification:
        return jsonify({'status': 'not_verified'})

    return jsonify(CollectibleVerificationService.get_verification_status(product_id))


@bp.route('/browse')
def browse_collectibles():
    """Browse verified collectibles"""
    form = CollectibleFilterForm()
    page = request.args.get('page', 1, type=int)

    query = CollectibleVerification.query.filter_by(verification_status='verified').join(Product)

    if form.collectible_type.data:
        query = query.filter(CollectibleVerification.collectible_type == form.collectible_type.data)

    if form.grader.data:
        query = query.filter(CollectibleVerification.grader == form.grader.data)

    collectibles = query.paginate(page=page, per_page=20)

    return render_template('collectibles/browse.html',
                          collectibles=collectibles, form=form)


@bp.route('/certificate-lookup', methods=['GET', 'POST'])
def certificate_lookup():
    """Public API for certificate lookup"""
    if request.method == 'POST':
        data = request.get_json()
        grader = data.get('grader')
        cert_number = data.get('certificate_number')

        if not grader or not cert_number:
            return jsonify({'error': 'Missing grader or certificate number'}), 400

        # Lookup certificate
        result = CollectibleVerificationService.lookup_with_api(grader, cert_number)

        # Check if already used in verified listing
        verification = CollectibleVerification.query.filter_by(
            certificate_number=cert_number,
            grader=grader,
            verification_status='verified'
        ).first()

        return jsonify({
            'api_result': result,
            'used_in_listing': verification is not None,
            'listing_product_id': verification.product_id if verification else None
        })

    return render_template('collectibles/lookup.html')


@bp.route('/admin/verify/<int:verification_id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def approve_verification(verification_id):
    """Admin approves a verification"""
    verification = CollectibleVerification.query.get_or_404(verification_id)

    result = CollectibleVerificationService.approve_manual_verification(
        verification_id=verification_id,
        admin_user=current_user.email
    )

    if result['status'] == 'success':
        flash(f"Verification approved for product #{verification.product_id}", 'success')
    else:
        flash(f"Error: {result.get('message')}", 'danger')

    return redirect(request.referrer or url_for('main.index'))


@bp.route('/admin/verify/<int:verification_id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def reject_verification(verification_id):
    """Admin rejects a verification"""
    verification = CollectibleVerification.query.get_or_404(verification_id)
    reason = request.form.get('reason', 'Certificate details do not match.')

    verification.verification_status = 'failed'
    verification.notes = f"Rejected by admin: {reason}"
    verification.verified_by = current_user.email
    verification.verification_date = datetime.utcnow()

    db.session.commit()

    log = VerificationLog(
        collectible_id=verification.id,
        action='manual_rejection',
        status='rejected',
        details=json.dumps({'reason': reason}),
        performed_by=current_user.email
    )
    db.session.add(log)
    db.session.commit()

    flash(f"Verification rejected for product #{verification.product_id}", 'warning')

    return redirect(request.referrer or url_for('main.index'))
