from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.domain.types import DayPart, LeaveType


class LeaveRequestForm(FlaskForm):
    type = SelectField("Type", choices=[(t.value, t.value) for t in LeaveType])
    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired()])
    day_part = SelectField(
        "Day part",
        choices=[("FULL", "Full day(s)"), ("AM", "AM only"), ("PM", "PM only")],
        default="FULL",
    )
    reason = StringField("Reason (optional)", validators=[Optional(), Length(max=300)])

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("End date is before start date.")

    def validate_day_part(self, field):
        if (
            field.data != DayPart.FULL.value
            and self.start_date.data
            and self.end_date.data
            and self.start_date.data != self.end_date.data
        ):
            raise ValidationError("A half-day off must be a single day.")
