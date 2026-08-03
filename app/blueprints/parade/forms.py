from flask_wtf import FlaskForm
from wtforms import DateField, SelectMultipleField, StringField
from wtforms.validators import DataRequired, Length, Optional

from app.blueprints.forms_shared import EndDateOrderMixin
from app.domain.types import ParticipantCategory


class McDeclarationForm(EndDateOrderMixin, FlaskForm):
    """Self-declared MC (owner decision 2026-07-31): dates and an optional
    remark, nothing else. Who it is for is `current_user` in the route, and
    type/day part/in camp are fixed (MC / FULL / out of camp) — a form field
    for any of them would be a field with exactly one legal answer.
    """

    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired()])
    remarks = StringField("Remarks (optional)", validators=[Optional(), Length(max=300)])


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
