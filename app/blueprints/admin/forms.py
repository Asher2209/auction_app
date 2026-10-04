from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length


class CategoryForm(FlaskForm):
    name = StringField("Category name", validators=[DataRequired(), Length(min=2, max=80)])


class ReasonForm(FlaskForm):
    reason = TextAreaField("Reason (shown to the seller)", validators=[DataRequired(), Length(min=5, max=500)])
