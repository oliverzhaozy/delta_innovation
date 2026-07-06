from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.domain.types import DayPart, DirectAbsenceType, StatusType

# Field name is `person_id` (not `person`) so obj= prefill on edit binds
# straight to the FK column, exactly like the enum-backed fields below need
# their .value re-coerced (mirrors admin/person_edit's pattern).
DAY_PART_CHOICES = [("FULL", "Full day(s)"), ("AM", "AM only"), ("PM", "PM only")]

# The 3-way in-camp select: DEFAULT resolves server-side against
# STATUS_IN_CAMP_DEFAULT[type]; IN/OUT are explicit overrides. Zero JS
# (TECH_PLAN P3a cut list) — the whole resolution is one dict lookup in the route.
IN_CAMP_CHOICES = [
    ("DEFAULT", "Default for type"),
    ("IN", "In camp"),
    ("OUT", "Out of camp"),
]


class StatusEntryForm(FlaskForm):
    person_id = SelectField("Person", coerce=int)
    type = SelectField("Type", choices=[(t.value, t.label) for t in StatusType])
    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired()])
    day_part = SelectField("Day part", choices=DAY_PART_CHOICES, default="FULL")
    in_camp = SelectField("In camp", choices=IN_CAMP_CHOICES, default="DEFAULT")
    remarks = StringField("Remarks (optional)", validators=[Optional(), Length(max=300)])

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("End date is before start date.")

    def validate_day_part(self, field):
        # Mirrors LeaveRequestForm: a half-day entry only makes sense for one day.
        if (
            field.data != DayPart.FULL.value
            and self.start_date.data
            and self.end_date.data
            and self.start_date.data != self.end_date.data
        ):
            raise ValidationError("A half-day entry must be a single day.")


class DirectAbsenceForm(FlaskForm):
    person_id = SelectField("Person", coerce=int)
    type = SelectField("Type", choices=[(t.value, t.label) for t in DirectAbsenceType])
    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired()])
    day_part = SelectField("Day part", choices=DAY_PART_CHOICES, default="FULL")
    # Required (unlike StatusEntryForm.remarks): a direct absence has no other
    # record of why a regular is away, so the reason must be keyed here.
    remarks = StringField("Remarks", validators=[DataRequired(), Length(max=300)])

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
            raise ValidationError("A half-day entry must be a single day.")
