from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, SelectMultipleField, StringField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.domain.types import DayPart, ParticipantCategory, StatusType

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


class FpBulkAddForm(FlaskForm):
    """Not-joining-FP bulk add (UI-19): categories + specific people (the same
    picker wire format as the calendar event form) and ONE required reason for
    everyone selected. The viewed date rides along as a plain hidden input in
    the template, not a form field here — it is route state (which day's page
    posted this), not user input to validate.
    """

    # "ALL" is a form-level pseudo-choice; the route expands every category to
    # concrete person ids at submit time — an FP row is per-person state for
    # one morning, so nothing category-shaped is ever stored.
    categories = SelectMultipleField(
        "Who's not joining",
        choices=[(c.value, c.label) for c in ParticipantCategory] + [("ALL", "All (everyone)")],
    )
    # Choices are the active roster at request time (set in routes.py).
    people = SelectMultipleField("People", coerce=int)
    reason = StringField("Reason", validators=[DataRequired(), Length(max=300)])
