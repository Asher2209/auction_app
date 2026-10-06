from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired, MultipleFileField
from wtforms import (
    StringField, SelectField, IntegerField, TextAreaField, BooleanField,
    DecimalField, SubmitField, MultipleFileField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange, ValidationError
from ...models import CardType


class CollectibleCardForm(FlaskForm):
    """Base form for collecting trading card information"""

    # Card type selection
    card_type_id = SelectField(
        'Card Type',
        coerce=int,
        validators=[DataRequired(message='Please select a card type')]
    )

    # Common card information
    card_name = StringField(
        'Card Name',
        validators=[
            DataRequired(),
            Length(min=2, max=255, message='Card name must be between 2 and 255 characters')
        ],
        render_kw={'placeholder': 'e.g., Charizard, Lionel Messi'}
    )

    manufacturer = StringField(
        'Manufacturer / Brand',
        validators=[
            Optional(),
            Length(max=100)
        ],
        render_kw={'placeholder': 'e.g., The Pokémon Company, Panini'}
    )

    set_name = StringField(
        'Set / Collection Name',
        validators=[
            Optional(),
            Length(max=100)
        ],
        render_kw={'placeholder': 'e.g., Base Set, 2022 FIFA World Cup'}
    )

    set_code = StringField(
        'Set Code',
        validators=[
            Optional(),
            Length(max=50)
        ],
        render_kw={'placeholder': 'e.g., BS, WC22'}
    )

    release_year = IntegerField(
        'Release Year',
        validators=[
            Optional(),
            NumberRange(min=1900, max=2100, message='Year must be between 1900 and 2100')
        ],
        render_kw={'placeholder': '1999'}
    )

    card_number = StringField(
        'Card Number',
        validators=[
            Optional(),
            Length(max=50)
        ],
        render_kw={'placeholder': 'e.g., 4/102, #10'}
    )

    rarity = StringField(
        'Rarity',
        validators=[
            Optional(),
            Length(max=50)
        ],
        render_kw={'placeholder': 'e.g., Rare Holo, Common, Ultra Rare'}
    )

    # Condition assessment
    condition = SelectField(
        'Condition',
        choices=[
            ('', '-- Select Condition --'),
            ('Poor', 'Poor'),
            ('Played', 'Played'),
            ('Good', 'Good'),
            ('Very Good', 'Very Good'),
            ('Excellent', 'Excellent'),
            ('Near Mint', 'Near Mint'),
            ('Mint', 'Mint'),
        ],
        validators=[DataRequired(message='Please select a condition')]
    )

    condition_notes = TextAreaField(
        'Detailed Condition Description',
        validators=[
            Optional(),
            Length(max=1000, message='Condition notes must be under 1000 characters')
        ],
        render_kw={
            'placeholder': 'Describe any wear, damage, or special features. Be honest about condition.',
            'rows': 4
        }
    )

    # Additional metadata
    language = SelectField(
        'Language',
        choices=[
            ('English', 'English'),
            ('Japanese', 'Japanese'),
            ('German', 'German'),
            ('French', 'French'),
            ('Spanish', 'Spanish'),
            ('Italian', 'Italian'),
            ('Portuguese', 'Portuguese'),
            ('Korean', 'Korean'),
            ('Chinese', 'Chinese'),
            ('Other', 'Other'),
        ],
        default='English',
        validators=[Optional()]
    )

    country = StringField(
        'Country/Region of Origin',
        validators=[
            Optional(),
            Length(max=50)
        ],
        render_kw={'placeholder': 'e.g., USA, Japan, Germany'}
    )

    edition = StringField(
        'Edition',
        validators=[
            Optional(),
            Length(max=100)
        ],
        render_kw={'placeholder': 'e.g., First Edition, Unlimited, Shadowless'}
    )

    # Grading information (optional)
    is_graded = BooleanField(
        'This card has been graded by a professional service',
        default=False
    )

    grading_company = SelectField(
        'Grading Company',
        choices=[
            ('', '-- Not graded --'),
            ('PSA', 'PSA (Professional Sports Authenticator)'),
            ('Beckett', 'Beckett (BGS/BVG)'),
            ('CGC', 'CGC (Certified Guaranty Company)'),
            ('SGC', 'SGC (Sportscard Guaranty)'),
        ],
        validators=[Optional()]
    )

    grade = StringField(
        'Grade',
        validators=[
            Optional(),
            Length(max=20, message='Grade must be under 20 characters')
        ],
        render_kw={'placeholder': 'e.g., PSA 9, Gem Mint 10, BGS 8.5'}
    )

    certification_number = StringField(
        'Certification Number',
        validators=[
            Optional(),
            Length(max=100, message='Certification number must be under 100 characters')
        ],
        render_kw={'placeholder': 'The grader\'s certificate number'}
    )

    certification_url = StringField(
        'Certification URL',
        validators=[
            Optional(),
            Length(max=500)
        ],
        render_kw={'placeholder': 'Link to grader\'s verification page (optional)'}
    )

    # Estimated value
    estimated_value = DecimalField(
        'Your Estimated Value',
        places=2,
        validators=[
            Optional(),
            NumberRange(min=0.01, max=10_000_000, message='Value must be between 0.01 and 10,000,000')
        ],
        render_kw={'placeholder': 'Your assessment of card value (for admin reference)'}
    )

    # Card images
    card_images = MultipleFileField(
        'Card Images',
        validators=[
            FileRequired('Please upload at least one image'),
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only (JPG, PNG, GIF)'),
        ],
        render_kw={
            'accept': 'image/*',
            'multiple': True,
            'help_text': 'Upload clear photos of card front, back, and grading slab if applicable'
        }
    )

    # Pokémon-specific fields (hidden by JavaScript unless card_type is Pokemon)
    pokemon_name = StringField(
        'Pokémon Name',
        validators=[Optional(), Length(max=100)],
        render_kw={'placeholder': 'e.g., Charizard, Blastoise'}
    )

    pokemon_hp = IntegerField(
        'HP (Hit Points)',
        validators=[Optional(), NumberRange(min=1, max=1000)],
        render_kw={'placeholder': 'e.g., 120'}
    )

    pokemon_holo_type = SelectField(
        'Holographic Type',
        choices=[
            ('', '-- Select --'),
            ('Holo', 'Holo'),
            ('Reverse Holo', 'Reverse Holo'),
            ('Non-Holo', 'Non-Holo'),
        ],
        validators=[Optional()]
    )

    pokemon_first_edition = BooleanField('First Edition', default=False)
    pokemon_shadowless = BooleanField('Shadowless', default=False)
    pokemon_promo = BooleanField('Promo Card', default=False)

    pokemon_illustrator = StringField(
        'Illustrator',
        validators=[Optional(), Length(max=100)],
        render_kw={'placeholder': 'Card artist/illustrator name'}
    )

    # Football/Soccer-specific fields (hidden by JavaScript unless card_type is Football)
    football_player_name = StringField(
        'Player Name',
        validators=[Optional(), Length(max=100)],
        render_kw={'placeholder': 'e.g., Lionel Messi, Cristiano Ronaldo'}
    )

    football_team = StringField(
        'Club / Team',
        validators=[Optional(), Length(max=100)],
        render_kw={'placeholder': 'e.g., PSG, Manchester United'}
    )

    football_national_team = StringField(
        'National Team',
        validators=[Optional(), Length(max=100)],
        render_kw={'placeholder': 'e.g., Argentina, Portugal'}
    )

    football_league = StringField(
        'League',
        validators=[Optional(), Length(max=100)],
        render_kw={'placeholder': 'e.g., Premier League, La Liga, Serie A'}
    )

    football_season = StringField(
        'Season',
        validators=[Optional(), Length(max=50)],
        render_kw={'placeholder': 'e.g., 2022-2023, 2021'}
    )

    football_is_rookie = BooleanField('Rookie Card', default=False)
    football_is_autograph = BooleanField('Autograph Card', default=False)
    football_is_relic = BooleanField('Relic / Memorabilia Card', default=False)
    football_is_numbered = BooleanField('Numbered Card', default=False)

    football_serial_number = StringField(
        'Serial Number',
        validators=[Optional(), Length(max=50)],
        render_kw={'placeholder': 'If numbered, e.g., 5/100'}
    )

    # General confirmation
    confirm_accuracy = BooleanField(
        'I confirm that all information above is accurate and complete',
        validators=[DataRequired(message='Please confirm accuracy of information')]
    )

    submit = SubmitField('Save Card Listing')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate card type choices
        active_types = CardType.query.filter_by(is_active=True).order_by(CardType.name)
        self.card_type_id.choices = [(t.id, t.name) for t in active_types]

    def validate_certification_number(self, field):
        """Validate that certification number is provided if graded"""
        if self.is_graded.data and self.grading_company.data and not field.data:
            raise ValidationError('Certification number is required for graded cards')

    def validate_grade(self, field):
        """Validate that grade is provided if graded"""
        if self.is_graded.data and self.grading_company.data and not field.data:
            raise ValidationError('Grade is required for graded cards')
