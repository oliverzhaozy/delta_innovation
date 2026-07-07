from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.domain.types import Appointment, CompanyRole, Rank, Service
from app.extensions import db, login_manager


def _values(enum_cls):
    # Store the enum's .value (e.g. "2LT"), not its Python name (TWO_LT).
    return [member.value for member in enum_cls]


class Person(UserMixin, db.Model):
    """One row per soldier; doubles as the login account (strict 1:1 at 40 users).

    Never hard-deleted: ORD/post-out sets is_active=False, which also blocks
    login via Flask-Login's is_active check.
    """

    __tablename__ = "person"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(120), nullable=False)
    rank = db.Column(db.Enum(Rank, values_callable=_values, name="rank"), nullable=False)
    appointment = db.Column(
        db.Enum(Appointment, values_callable=_values, name="appointment"), nullable=False
    )
    company_role = db.Column(
        db.Enum(CompanyRole, values_callable=_values, name="company_role"), nullable=True
    )
    platoon = db.Column(db.Integer, nullable=True)  # 1-3; OC/SM/2IC have none
    # Optional, S3-keyed, for the manning document only (owner decision (q)
    # 2026-07-07 revised the no-phones rule — docs/MANNING_FORMATS.md).
    phone = db.Column(db.String(20), nullable=True)
    service = db.Column(db.Enum(Service, values_callable=_values, name="service"), nullable=False)
    stay_out = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_pw = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Person {self.username} {self.rank.value} {self.appointment.value}>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Person, int(user_id))
