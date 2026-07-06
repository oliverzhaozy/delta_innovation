from flask_wtf import FlaskForm
from wtforms import (
    DateTimeLocalField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional, ValidationError
from wtforms.widgets import CheckboxInput, ListWidget

from app.domain.types import Calendar, ParticipantCategory


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
    # Include-categories only — category *exclude* is a TECH_PLAN cut for this
    # picker (the schema/pure resolver still support it): "everyone except
    # NSF" is spelled by tagging REGULAR instead.
    categories = SelectMultipleField(
        "Categories",
        choices=[(c.value, c.label) for c in ParticipantCategory],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInput(),
    )
    # Choices are the active roster at request time (set in routes.py, not
    # here) — who's active/what platoon they're in changes day to day.
    include_people = SelectMultipleField(
        "Also include",
        coerce=int,
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInput(),
    )
    except_people = SelectMultipleField(
        "Except",
        coerce=int,
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInput(),
    )

    def validate_end_dt(self, field):
        # Mirrors the model's ck_event_dt_order — catch it in the form too so
        # the page re-renders with a field error instead of a 500 from the DB.
        if self.start_dt.data and field.data and field.data <= self.start_dt.data:
            raise ValidationError("End must be after start.")

    def validate_except_people(self, field):
        # Server-side only (no JS): a person can't be both carved in and
        # carved out of the same event — the model's unique-per-person
        # constraint would catch this too, but a 500 isn't the UX we want.
        if set(self.include_people.data or []) & set(field.data or []):
            raise ValidationError("A person can't be both included and excepted.")
