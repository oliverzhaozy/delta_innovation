from flask_wtf import FlaskForm
from wtforms import DateTimeLocalField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.domain.types import Calendar


class EventForm(FlaskForm):
    calendar = SelectField("Calendar", choices=[(c.value, c.label) for c in Calendar])
    title = StringField("Title", validators=[DataRequired(), Length(max=120)])
    start_dt = DateTimeLocalField(
        "Start", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    end_dt = DateTimeLocalField(
        "End", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    notes = TextAreaField("Notes (optional)", validators=[Optional(), Length(max=500)])

    def validate_end_dt(self, field):
        # Mirrors the model's ck_event_dt_order — catch it in the form too so
        # the page re-renders with a field error instead of a 500 from the DB.
        if self.start_dt.data and field.data and field.data <= self.start_dt.data:
            raise ValidationError("End must be after start.")
