from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Regexp

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
    is_admin = BooleanField("Admin access")
    is_active = BooleanField("Active", default=True)
