from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DecimalField, SelectField, SelectMultipleField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError

from app.domain.types import BalanceKind, ParticipantCategory

# The bulk-award picker's four groups: All NSFs + the three platoons. No
# Regulars group (their off/leave lives in ARCTIC FOE) and no ALL/COMMAND_TEAM
# pseudo-choices — "All NSFs" is the everyone-selector here, so the picker's
# top rows are hidden. The route builds its picker_groups from this same tuple.
BULK_AWARD_CATEGORIES = (
    ParticipantCategory.NSF,
    ParticipantCategory.PLATOON_1,
    ParticipantCategory.PLATOON_2,
    ParticipantCategory.PLATOON_3,
)


class AmountForm(FlaskForm):
    """The amount half of every ledger write: how many days, and why.

    Both ledger forms below carry it identically, so it lives once — the
    half-day rule and its message must not become two rules that drift. Neither
    template iterates its form, so inheriting these fields does not move them:
    every field is rendered by name.
    """

    days = DecimalField(
        "Days", places=1, validators=[DataRequired(), NumberRange(min=0.5, max=30)]
    )
    reason = StringField("Reason", validators=[DataRequired(), Length(max=300)])

    def validate_days(self, field):
        # Ledger is integer half-days: only whole or half days are storable.
        if field.data is not None and (field.data * 2) % 1 != Decimal(0):
            raise ValidationError("Use whole or half days (e.g. 1, 1.5).")


class AdjustmentForm(AmountForm):
    kind = SelectField("Balance", choices=[(k.value, k.value) for k in BalanceKind])
    direction = SelectField("Action", choices=[("add", "Add"), ("deduct", "Deduct")])


class BulkAwardForm(AmountForm):
    """Credit one OFF/OIL amount to many NSFs in one submit (add only). The
    categories+people picker uses the same wire format as FpBulkAddForm; the
    route sets `people.choices` to the NSF roster and expands categories to
    concrete ids at submit time (nothing category-shaped is ever stored).
    """

    # Only the four picker groups are valid choices (no ALL/COMMAND_TEAM): a
    # stale "ALL"/"COMMAND_TEAM" POST fails choice validation and re-renders
    # with a field error, which is the intended behavior.
    categories = SelectMultipleField(
        "Who to award",
        choices=[(c.value, c.label) for c in BULK_AWARD_CATEGORIES],
    )
    # Choices are the NSF active roster at request time (set in routes.py).
    people = SelectMultipleField("People", coerce=int)
    kind = SelectField("Balance", choices=[(k.value, k.value) for k in BalanceKind])
