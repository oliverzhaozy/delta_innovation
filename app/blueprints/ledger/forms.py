from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DecimalField, SelectField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError

from app.domain.types import BalanceKind


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
