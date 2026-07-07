from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, StringField
from wtforms.validators import DataRequired, InputRequired, Length, ValidationError

from app.domain.types import Meal


class MealAdjustmentForm(FlaskForm):
    """S4's manual ± on one meal. The viewed date rides along as a plain hidden
    input in the template, not a form field here — route state, not user input
    to validate (FpQuickAddForm's convention).
    """

    meal = SelectField("Meal", choices=[(m.value, m.label) for m in Meal])
    # InputRequired, not DataRequired: 0 is falsy and must reach the explicit
    # validator below so the keyer gets a real message, not "field required".
    delta = IntegerField("Adjustment (±)", validators=[InputRequired()])
    reason = StringField("Reason", validators=[DataRequired(), Length(max=300)])

    def validate_delta(self, field):
        if field.data == 0:
            raise ValidationError("A zero adjustment changes nothing — key the actual ±.")
