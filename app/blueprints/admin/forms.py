from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.domain.types import Appointment, CompanyRole, Rank, Service


class PersonForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(max=64),
            Regexp(r"^[a-z0-9_]+$", message="Lowercase letters, digits and underscores only."),
        ],
    )
    display_name = StringField("Display name", validators=[DataRequired(), Length(max=120)])
    # Optional, for the manning document only (owner decision (q) 2026-07-07).
    phone = StringField("Phone (manning doc)", validators=[Optional(), Length(max=20)])
    rank = SelectField("Rank", choices=[(r.value, r.value) for r in Rank])
    appointment = SelectField(
        "Appointment", choices=[(a.value, a.label) for a in Appointment]
    )
    company_role = SelectField(
        "Company role",
        choices=[("", "—")] + [(r.value, r.value) for r in CompanyRole],
    )
    platoon = SelectField(
        "Platoon", choices=[("", "—"), ("1", "1"), ("2", "2"), ("3", "3")]
    )
    service = SelectField("Service", choices=[(s.value, s.value) for s in Service])
    stay_out = BooleanField("Stay out")
    duty_exempt = BooleanField("Exempt from duty (COS/CDO-S pools)")
    meals_opt_in = BooleanField("Counted for meal indents (regulars opt in; NSFs always counted)")
    is_admin = BooleanField("Admin access")
