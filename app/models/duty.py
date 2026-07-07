from app.domain.dates import now_sgt
from app.domain.types import Duty, DutyState
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class DutyAssignment(db.Model):
    """One holder per (date, duty). The UNIQUE constraint is a data-corruption
    backstop, not a judgment call: two COS on one night is impossible, so the
    schema says so. PROPOSED rows are drafts (regeneration replaces them
    freely); CONFIRMED rows are the roster of record that parades, meals, and
    rotating rights read (P4.7/P4.8).
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
    state = db.Column(
        db.Enum(DutyState, values_callable=_values, name="duty_state"), nullable=False
    )
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    person = db.relationship("Person", foreign_keys=[person_id])
    created_by = db.relationship("Person", foreign_keys=[created_by_id])
    confirmed_by = db.relationship("Person", foreign_keys=[confirmed_by_id])

    def __repr__(self):
        return f"<DutyAssignment {self.id} {self.date} {self.duty.value} {self.state.value}>"


class DutySwapLog(db.Model):
    """Append-only record of validated 1-for-1 swaps (ledger posture): no
    update or delete function or route exists anywhere for this model, and no
    uniqueness — swapping back is a second row, and the pair IS the audit
    trail. One `duty` column, not two: the COS and CDO/S pools are disjoint,
    so a validated swap is always same-duty by construction.
    """

    __tablename__ = "duty_swap_log"

    id = db.Column(db.Integer, primary_key=True)
    person_a_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    person_b_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    date_a = db.Column(db.Date, nullable=False)
    date_b = db.Column(db.Date, nullable=False)
    duty = db.Column(db.Enum(Duty, values_callable=_values, name="duty"), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    person_a = db.relationship("Person", foreign_keys=[person_a_id])
    person_b = db.relationship("Person", foreign_keys=[person_b_id])
    actor = db.relationship("Person", foreign_keys=[actor_id])

    def __repr__(self):
        return f"<DutySwapLog {self.id} {self.duty.value} {self.date_a}<->{self.date_b}>"
