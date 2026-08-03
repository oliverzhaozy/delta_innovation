from flask_wtf import FlaskForm
from wtforms import DateField, StringField
from wtforms.validators import DataRequired, Length

from app.blueprints.forms_shared import EndDateOrderMixin


class OverseasDeclarationForm(EndDateOrderMixin, FlaskForm):
    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired()])
    # Country/city level only — data minimization rule (CLAUDE.md).
    destination = StringField("Destination", validators=[DataRequired(), Length(max=100)])
