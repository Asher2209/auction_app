from flask_wtf import FlaskForm
from wtforms import TextAreaField
from wtforms.validators import DataRequired, Length


class ReasonForm(FlaskForm):
    reason = TextAreaField("Reason (shown to the seller)", validators=[DataRequired(), Length(min=5, max=500)])
