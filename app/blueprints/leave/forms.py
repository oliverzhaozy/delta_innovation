from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.blueprints.forms_shared import EndDateOrderMixin
from app.domain.types import DayPart, LeaveType


class LeaveRequestForm(EndDateOrderMixin, FlaskForm):
    type = SelectField("Type", choices=[(t.value, t.value) for t in LeaveType])
    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired()])
    day_part = SelectField(
        "Day part",
        choices=[("FULL", "Full day(s)"), ("AM", "AM only"), ("PM", "PM only")],
        default="FULL",
    )
    reason = StringField("Reason (optional)", validators=[Optional(), Length(max=300)])

    def validate_day_part(self, field):
        if (
            field.data != DayPart.FULL.value
            and self.start_date.data
            and self.end_date.data
            and self.start_date.data != self.end_date.data
        ):
            raise ValidationError("A half-day off must be a single day.")


class EarlyReturnForm(FlaskForm):
    """Amend an APPROVED multi-day request to an earlier last day. The service
    enforces the range (start ≤ new_end < old_end); this just parses the date."""

    new_end_date = DateField("Early return — new last day", validators=[DataRequired()])
