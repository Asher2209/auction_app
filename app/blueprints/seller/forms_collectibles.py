from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired, MultipleFileField
from wtforms import StringField, SelectField, IntegerField, TextAreaField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, NumberRange, ValidationError
from ...models import CollectibleVerification, SupportedGrader


class CollectibleVerificationForm(FlaskForm):
    """Form for adding collectible verification to a product listing"""

    # What type of collectible?
    collectible_type = SelectField(
        'Type of Collectible',
        choices=[
            ('trading_card', 'Graded Trading Card (PSA, Beckett, CGC, SGC)'),
            ('coin', 'Graded Coin (PCGS, NGC)'),
            ('autograph', 'Autograph/Memorabilia (PSA/DNA, JSA, Beckett)'),
            ('comic', 'Graded Comic (CGC, CBCS)'),
            ('banknote', 'Graded Banknote (PMG, PCGS)'),
            ('video_game', 'Graded Video Game (WATA, CGC Games)'),
            ('jewelry', 'Hallmarked Jewelry (BIS HUID)'),
        ],
        validators=[DataRequired()]
    )

    # Which grading company certified it?
    grader = SelectField(
        'Grading Company',
        choices=[
            ('PSA', 'PSA (Professional Sports Authenticator)'),
            ('Beckett', 'Beckett (BGS/BVG)'),
            ('CGC', 'CGC (Certified Guaranty Company)'),
            ('SGC', 'SGC (Sportscard Guaranty)'),
            ('PCGS', 'PCGS (Professional Coin Grading Service)'),
            ('NGC', 'NGC (Numismatic Guaranty Company)'),
            ('PMG', 'PMG (Paper Money Guaranty)'),
            ('JSA', 'JSA (James Spence Authentication)'),
            ('PSA/DNA', 'PSA/DNA (PSA Autograph Authentication)'),
            ('CBCS', 'CBCS (Certified Guaranty Company - Comics)'),
            ('WATA', 'WATA (Video Game Authentication)'),
            ('CGC Games', 'CGC Games (Video Game Grading)'),
            ('BIS', 'BIS (Bureau of Indian Standards - Jewelry)'),
        ],
        validators=[DataRequired()]
    )

    # Certificate/Serial number
    certificate_number = StringField(
        'Certificate Number',
        validators=[
            DataRequired(),
            Length(min=3, max=100, message='Certificate number must be 3-100 characters')
        ],
        render_kw={"placeholder": "e.g., PSA123456789 or PCGS12345678"}
    )

    # Grade assigned
    grade = StringField(
        'Grade',
        validators=[
            Optional(),
            Length(max=20, message='Grade must be less than 20 characters')
        ],
        render_kw={"placeholder": "e.g., PSA 10, Gem MT 9, GEM MS65"}
    )

    # Year of issue/manufacture
    year = IntegerField(
        'Year',
        validators=[
            Optional(),
            NumberRange(min=1800, max=2024, message='Year must be between 1800 and 2024')
        ],
        render_kw={"placeholder": "e.g., 1999"}
    )

    # Item name from grader (what they certified)
    grader_item_name = StringField(
        'Item Name (as listed on certificate)',
        validators=[
            Optional(),
            Length(max=255, message='Item name must be less than 255 characters')
        ],
        render_kw={"placeholder": "e.g., Pokémon Charizard Base Set #4"}
    )

    # Photos of the slab/certificate
    slab_photos = MultipleFileField(
        'Photos of Slab/Certificate',
        validators=[
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only (JPG, PNG, GIF)'),
        ],
        render_kw={"accept": "image/*", "multiple": True}
    )

    # Additional notes
    notes = TextAreaField(
        'Additional Information',
        validators=[
            Optional(),
            Length(max=1000, message='Notes must be less than 1000 characters')
        ],
        render_kw={"placeholder": "Any additional details about the item or certificate", "rows": 4}
    )

    # Confirmation
    confirm_accuracy = BooleanField(
        'I confirm that the certificate information above is accurate and matches the item being listed',
        validators=[DataRequired()]
    )

    submit = SubmitField('Verify Certificate')

    def validate_certificate_number(self, field):
        """Check if certificate already used"""
        existing = CollectibleVerification.query.filter_by(
            certificate_number=field.data.strip(),
            grader=self.grader.data
        ).first()

        if existing and existing.product_id != self.product_id:
            raise ValidationError(
                f'Certificate {field.data} is already registered with another product. '
                'If this is a duplicate entry, contact support.'
            )


class CollectiblePhotoVerificationForm(FlaskForm):
    """Form for uploading additional photos for manual verification"""

    slab_photos = MultipleFileField(
        'Upload Slab/Certificate Photos',
        validators=[
            FileRequired('Please upload at least one photo'),
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only (JPG, PNG, GIF)'),
        ],
        render_kw={"accept": "image/*", "multiple": True}
    )

    photo_notes = TextAreaField(
        'Notes about photos',
        validators=[Optional(), Length(max=500)],
        render_kw={"placeholder": "Describe what each photo shows", "rows": 3}
    )

    submit = SubmitField('Submit Photos')


class CollectibleFilterForm(FlaskForm):
    """Filter form for browsing verified collectibles"""

    collectible_type = SelectField(
        'Collectible Type',
        choices=[
            ('', 'All Types'),
            ('trading_card', 'Trading Cards'),
            ('coin', 'Coins'),
            ('autograph', 'Autographs/Memorabilia'),
            ('comic', 'Comics'),
            ('banknote', 'Banknotes'),
            ('video_game', 'Video Games'),
            ('jewelry', 'Jewelry'),
        ],
        validators=[Optional()]
    )

    grader = SelectField(
        'Grading Company',
        choices=[
            ('', 'All Graders'),
            ('PSA', 'PSA'),
            ('Beckett', 'Beckett'),
            ('CGC', 'CGC'),
            ('PCGS', 'PCGS'),
            ('NGC', 'NGC'),
            ('PSA/DNA', 'PSA/DNA'),
            ('JSA', 'JSA'),
        ],
        validators=[Optional()]
    )

    min_grade = SelectField(
        'Minimum Grade',
        choices=[
            ('', 'Any'),
            ('1', '1'),
            ('2', '2'),
            ('3', '3'),
            ('4', '4'),
            ('5', '5'),
            ('6', '6'),
            ('7', '7'),
            ('8', '8'),
            ('9', '9'),
            ('10', '10'),
        ],
        validators=[Optional()]
    )

    verified_only = BooleanField('Verified Only', default=True)

    submit = SubmitField('Filter')
