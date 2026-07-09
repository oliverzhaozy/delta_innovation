from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.domain.events import is_valid_label
from app.domain.types import Calendar, ParticipantCategory


class EventForm(FlaskForm):
    calendar = SelectField("Calendar", choices=[(c.value, c.label) for c in Calendar])
    title = StringField("Title", validators=[DataRequired(), Length(max=120)])
    all_day = BooleanField("All day")
    start_dt = DateTimeLocalField(
        "Start", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    end_dt = DateTimeLocalField(
        "End", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    # Labels are optional and calendar-specific; choices are set at request time
    # (routes._set_label_choices). validate_choice=False lets an absent/empty
    # value pass — validate_label enforces the calendar pairing instead.
    label = SelectField("Label", validators=[Optional()], validate_choice=False)
    notes = TextAreaField("Notes (optional)", validators=[Optional(), Length(max=500)])
    # Include-categories only — category *exclude* is a TECH_PLAN cut for this
    # picker (the schema/pure resolver still support it): "everyone except
    # NSF" is spelled by tagging REGULAR instead. "ALL" is a form-level
    # pseudo-choice the route expands to NSF+REGULAR on save (UI-11); it is not
    # a stored ParticipantCategory. The dropdowns/checkboxes are hand-rendered
    # in the template, so no widget/option_widget here.
    categories = SelectMultipleField(
        "Participants",
        choices=[(c.value, c.label) for c in ParticipantCategory] + [("ALL", "All (everyone)")],
    )
    # Choices are the active roster at request time (set in routes.py, not
    # here) — who's active/what platoon they're in changes day to day. Rendered
    # by hand across the grouped dropdowns; coerce=int so ids match Person.id.
    people = SelectMultipleField("People", coerce=int)

    def validate_end_dt(self, field):
        # Mirrors the model's ck_event_dt_order — catch it in the form too so
        # the page re-renders with a field error instead of a 500 from the DB.
        # For all-day the time is ignored (the route normalizes it), so a
        # single-day all-day event is fine — only the DATES must not go backwards.
        if not (self.start_dt.data and field.data):
            return
        if self.all_day.data:
            if field.data.date() < self.start_dt.data.date():
                raise ValidationError("End day must not be before the start day.")
        elif field.data <= self.start_dt.data:
            raise ValidationError("End must be after start.")

    def validate_label(self, field):
        # The label must belong to the chosen calendar's set (empty is fine).
        # self.calendar.data is the plain value string ("TP"/"ARCTIC").
        if not field.data:
            return
        try:
            calendar = Calendar(self.calendar.data)
        except ValueError:
            return  # a bad calendar is reported by the calendar field's own check
        if not is_valid_label(calendar, field.data):
            raise ValidationError("That label isn't available for this calendar.")
