from app.domain.dates import now_sgt
from app.domain.types import Duty
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class DutyAssignment(db.Model):
    """One holder per (date, duty). The UNIQUE constraint is a data-corruption
    backstop, not a judgment call: two COS on one night is impossible, so the
    schema says so. Every row is live the moment it exists (owner 2026-07-27 —
    the PROPOSED/CONFIRMED draft step is gone): parades, meals, and rotating
    rights read them all.

    `is_manual` marks a human's pick. Regeneration replans AROUND manual rows
    and replaces the generator's own — the flag is what makes "generate again"
    safe after the PS has fixed a slot by hand.
    """

    __tablename__ = "duty_assignment"
    __table_args__ = (
        db.UniqueConstraint("date", "duty", name="uq_duty_date_duty"),
        db.Index("ix_duty_date", "date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    duty = db.Column(db.Enum(Duty, values_callable=_values, name="duty"), nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    is_manual = db.Column(db.Boolean, nullable=False, default=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    person = db.relationship("Person", foreign_keys=[person_id])
    created_by = db.relationship("Person", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<DutyAssignment {self.id} {self.date} {self.duty.value}>"


class DutyBlockedDay(db.Model):
    """A working day the unit needs no COS/CDO-S on (owner 2026-07-27).

    Persisted rather than derived because it is a statement, not a fact of the
    calendar: regeneration and the roster grid must read the same one. The
    UNIQUE date is the duplicate-block guard — the service inserts and catches
    IntegrityError instead of pre-checking. Blocking deletes that date's
    assignments, so a block never hides a holder.
    """

    __tablename__ = "duty_blocked_day"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    created_by = db.relationship("Person", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<DutyBlockedDay {self.id} {self.date}>"
