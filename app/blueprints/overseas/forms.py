from flask_wtf import FlaskForm
from wtforms import DateField, StringField
from wtforms.validators import DataRequired, Length, ValidationError


class OverseasDeclarationForm(FlaskForm):
    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired()])
    # Country/city level only — data minimization rule (CLAUDE.md).
    destination = StringField("Destination", validators=[DataRequired(), Length(max=100)])

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("End date is before start date.")
