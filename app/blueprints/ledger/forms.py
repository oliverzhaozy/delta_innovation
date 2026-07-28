from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DecimalField, SelectField, SelectMultipleField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError

from app.domain.types import BalanceKind, ParticipantCategory


class AdjustmentForm(FlaskForm):
    kind = SelectField("Balance", choices=[(k.value, k.value) for k in BalanceKind])
    direction = SelectField("Action", choices=[("add", "Add"), ("deduct", "Deduct")])
    days = DecimalField(
        "Days", places=1, validators=[DataRequired(), NumberRange(min=0.5, max=30)]
    )
    reason = StringField("Reason", validators=[DataRequired(), Length(max=300)])

    def validate_days(self, field):
        # Ledger is integer half-days: only whole or half days are storable.
        if field.data is not None and (field.data * 2) % 1 != Decimal(0):
            raise ValidationError("Use whole or half days (e.g. 1, 1.5).")


class BulkAwardForm(FlaskForm):
    """Credit one OFF/OIL amount to many NSFs in one submit (add only). The
    categories+people picker uses the same wire format as FpBulkAddForm; the
    route sets `people.choices` to the NSF roster and expands categories to
    concrete ids at submit time (nothing category-shaped is ever stored).
    """

    # "ALL" is a form-level pseudo-choice expanded in the route. COMMAND_TEAM
    # rides along as a category value (the picker template renders its box);
    # against the NSF roster it resolves to NSF command appointments only.
    categories = SelectMultipleField(
        "Who to award",
        choices=[(c.value, c.label) for c in ParticipantCategory] + [("ALL", "All (everyone)")],
    )
    # Choices are the NSF active roster at request time (set in routes.py).
    people = SelectMultipleField("People", coerce=int)
    kind = SelectField("Balance", choices=[(k.value, k.value) for k in BalanceKind])
    days = DecimalField(
        "Days", places=1, validators=[DataRequired(), NumberRange(min=0.5, max=30)]
    )
    reason = StringField("Reason", validators=[DataRequired(), Length(max=300)])

    def validate_days(self, field):
        # Ledger is integer half-days: only whole or half days are storable.
        if field.data is not None and (field.data * 2) % 1 != Decimal(0):
            raise ValidationError("Use whole or half days (e.g. 1, 1.5).")
