from app.domain.dates import now_sgt
from app.domain.types import DayPart, DirectAbsenceType
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class DirectAbsence(db.Model):
    """S3-keyed absence for regulars (OC/SM/2IC/P2IC), who sit outside the
    leave-request flow (owner decision (b)). No ledger effect. No in_camp
    flag — a direct absence is out of camp by definition; in-camp exceptions
    are what status_entry's in_camp is for.
    """

    __tablename__ = "direct_absence"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False, index=True)
    type = db.Column(
        db.Enum(DirectAbsenceType, values_callable=_values, name="direct_absence_type"),
        nullable=False,
    )
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    day_part = db.Column(
        db.Enum(DayPart, values_callable=_values, name="day_part"),
        nullable=False,
        default=DayPart.FULL,
    )
    # Nullable at the model level; the P3a.5 form makes this mandatory for
    # direct absences (UI concern, not schema).
    remarks = db.Column(db.String(300))
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    person = db.relationship("Person", foreign_keys=[person_id])
    created_by = db.relationship("Person", foreign_keys=[created_by_id])

    __table_args__ = (
        db.CheckConstraint("start_date <= end_date", name="ck_direct_absence_date_order"),
        # Half-day only makes sense for a single day (mirrors leave_request).
        db.CheckConstraint(
            "day_part = 'FULL' OR start_date = end_date",
            name="ck_direct_absence_half_day_single_day",
        ),
        db.Index("ix_direct_absence_range", "start_date", "end_date"),
    )

    def __repr__(self):
        return f"<DirectAbsence {self.id} p{self.person_id} {self.type.value}>"
