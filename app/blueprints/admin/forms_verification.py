from flask_wtf import FlaskForm
from wtforms import (
    SelectField, TextAreaField, BooleanField, SubmitField, StringField,
    MultipleFileField
)
from wtforms.validators import DataRequired, Optional, Length


class CardVerificationChecklistForm(FlaskForm):
    """Admin checklist for verifying collectible cards"""

    # Card identity verification
    card_identity_result = SelectField(
        'Card Identity Verified',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Verified'),
            ('needs_review', '⚠ Needs Review'),
            ('failed', '✗ Failed'),
        ],
        validators=[DataRequired()]
    )
    card_identity_notes = TextAreaField(
        'Card Identity Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2, 'placeholder': 'Notes about card identity verification'}
    )

    # Set verification
    set_checked_result = SelectField(
        'Set / Collection Verified',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Verified'),
            ('needs_review', '⚠ Needs Review'),
            ('failed', '✗ Failed'),
        ],
        validators=[DataRequired()]
    )
    set_checked_notes = TextAreaField(
        'Set Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2}
    )

    # Card number verification
    card_number_result = SelectField(
        'Card Number Verified',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Verified'),
            ('needs_review', '⚠ Needs Review'),
            ('failed', '✗ Failed'),
        ],
        validators=[DataRequired()]
    )
    card_number_notes = TextAreaField(
        'Card Number Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2}
    )

    # Manufacturer verification
    manufacturer_result = SelectField(
        'Manufacturer Verified',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Verified'),
            ('needs_review', '⚠ Needs Review'),
            ('failed', '✗ Failed'),
        ],
        validators=[DataRequired()]
    )
    manufacturer_notes = TextAreaField(
        'Manufacturer Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2}
    )

    # Image quality review
    images_reviewed_result = SelectField(
        'Images Reviewed',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Clear & Complete'),
            ('needs_review', '⚠ Unclear / Incomplete'),
            ('failed', '✗ Unacceptable Quality'),
        ],
        validators=[DataRequired()]
    )
    images_reviewed_notes = TextAreaField(
        'Image Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2, 'placeholder': 'E.g., "Front and back clear, grading slab visible"'}
    )

    # Condition review
    condition_reviewed_result = SelectField(
        'Condition Assessment Reviewed',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Accurate'),
            ('needs_review', '⚠ Questionable'),
            ('failed', '✗ Misrepresented'),
        ],
        validators=[DataRequired()]
    )
    condition_reviewed_notes = TextAreaField(
        'Condition Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2, 'placeholder': 'Does the condition claim match the photos?'}
    )

    # Grading certificate verification (if applicable)
    grading_checked_result = SelectField(
        'Grading Certificate Verified',
        choices=[
            ('', '-- N/A or Select --'),
            ('verified', '✓ Verified'),
            ('needs_review', '⚠ Needs Review'),
            ('failed', '✗ Invalid'),
        ],
        validators=[Optional()]
    )
    grading_checked_notes = TextAreaField(
        'Grading Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2, 'placeholder': 'E.g., "PSA cert verified at psacard.com"'}
    )

    # Seller information verification
    seller_info_reviewed_result = SelectField(
        'Seller Information Reviewed',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Verified'),
            ('needs_review', '⚠ Needs Review'),
            ('failed', '✗ Suspicious'),
        ],
        validators=[DataRequired()]
    )
    seller_info_reviewed_notes = TextAreaField(
        'Seller Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2}
    )

    # Counterfeit check
    counterfeit_check_result = SelectField(
        'Counterfeit Risk Assessment',
        choices=[
            ('', '-- Select --'),
            ('verified', '✓ Low Risk'),
            ('needs_review', '⚠ Moderate Risk'),
            ('failed', '✗ High Risk / Suspected Counterfeit'),
        ],
        validators=[DataRequired()]
    )
    counterfeit_check_notes = TextAreaField(
        'Counterfeit Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 2, 'placeholder': 'Any red flags? Printing issues, material concerns, etc.'}
    )

    # Overall admin notes
    overall_notes = TextAreaField(
        'Overall Verification Notes',
        validators=[Optional(), Length(max=1000)],
        render_kw={'rows': 4, 'placeholder': 'Summary of verification, any concerns, recommendations for next steps'}
    )

    submit = SubmitField('Save Verification Checklist')


class CardApprovalForm(FlaskForm):
    """Admin form to approve a card for auction"""

    approval_notes = TextAreaField(
        'Approval Notes',
        validators=[Optional(), Length(max=500)],
        render_kw={
            'rows': 3,
            'placeholder': 'Optional notes for the seller (not shown publicly)'
        }
    )

    submit = SubmitField('✓ Approve Card')


class CardRejectionForm(FlaskForm):
    """Admin form to reject a card listing"""

    rejection_reason = SelectField(
        'Rejection Reason',
        choices=[
            ('', '-- Select Reason --'),
            ('Incorrect card details', 'Incorrect card details'),
            ('Poor-quality images', 'Poor-quality images'),
            ('Suspected counterfeit', 'Suspected counterfeit'),
            ('Missing information', 'Missing information'),
            ('Serial number mismatch', 'Serial number mismatch'),
            ('Condition does not match description', 'Condition does not match description'),
            ('Authentication information insufficient', 'Authentication information insufficient'),
            ('Potentially misleading listing', 'Potentially misleading listing'),
            ('Other reason', 'Other reason'),
        ],
        validators=[DataRequired(message='Please select a rejection reason')]
    )

    rejection_details = TextAreaField(
        'Rejection Details',
        validators=[
            DataRequired(message='Please provide details'),
            Length(min=10, max=500, message='Rejection details must be 10-500 characters')
        ],
        render_kw={
            'rows': 4,
            'placeholder': 'Explain why the card is being rejected. The seller will see this message.'
        }
    )

    allow_resubmit = BooleanField(
        'Allow seller to resubmit after making corrections',
        default=True
    )

    submit = SubmitField('✗ Reject Card')


class CardMoreInfoForm(FlaskForm):
    """Admin form to request more information from seller"""

    info_request = SelectField(
        'Information Needed',
        choices=[
            ('', '-- Select --'),
            ('Better card images', 'Please upload clearer images'),
            ('Clarify condition', 'Please clarify condition assessment'),
            ('Verify grading certificate', 'Please verify grading certificate details'),
            ('Provide set information', 'Please provide complete set information'),
            ('Upload grading slab photo', 'Please upload photo of grading slab'),
            ('Clarify card number', 'Please clarify card number'),
            ('Custom request', 'Custom request (specify below)'),
        ],
        validators=[DataRequired()]
    )

    custom_request = TextAreaField(
        'Specific Request',
        validators=[Optional(), Length(max=500)],
        render_kw={
            'rows': 3,
            'placeholder': 'If custom request selected, specify what information is needed'
        }
    )

    message = TextAreaField(
        'Message to Seller',
        validators=[
            DataRequired(message='Please provide a message'),
            Length(min=10, max=500, message='Message must be 10-500 characters')
        ],
        render_kw={
            'rows': 4,
            'placeholder': 'The seller will see this message. Be specific about what you need.'
        }
    )

    submit = SubmitField('⚠ Request More Information')


class BulkVerificationActionForm(FlaskForm):
    """Admin form for bulk verification actions"""

    action = SelectField(
        'Bulk Action',
        choices=[
            ('', '-- Select Action --'),
            ('approve_all', 'Approve All Selected'),
            ('reject_all', 'Reject All Selected'),
            ('request_info_all', 'Request Info From All Selected'),
        ],
        validators=[DataRequired()]
    )

    reason_for_action = TextAreaField(
        'Reason / Details',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': 3}
    )

    submit = SubmitField('Execute Bulk Action')
