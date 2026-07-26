from app.domain.dates import now_sgt
from app.domain.types import DayPart, StatusType
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class StatusEntry(db.Model):
    """COS-keyed date-ranged exception (MC/other).

    No ledger effect — this is a presence input for the Phase 3 parade engine,
    not a leave type. `in_camp` is per-row, not derived from `type`: the same
    type can be keyed either way (STATUS_IN_CAMP_DEFAULT is a form default).
    """

    __tablename__ = "status_entry"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False, index=True)
    type = db.Column(db.Enum(StatusType, values_callable=_values, name="status_type"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    day_part = db.Column(
        db.Enum(DayPart, values_callable=_values, name="day_part"),
        nullable=False,
        default=DayPart.FULL,
    )
    in_camp = db.Column(db.Boolean, nullable=False)
    remarks = db.Column(db.String(300))
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    person = db.relationship("Person", foreign_keys=[person_id])
    created_by = db.relationship("Person", foreign_keys=[created_by_id])

    __table_args__ = (
        db.CheckConstraint("start_date <= end_date", name="ck_status_date_order"),
        # Half-day only makes sense for a single day (mirrors leave_request).
        db.CheckConstraint(
            "day_part = 'FULL' OR start_date = end_date", name="ck_status_half_day_single_day"
        ),
        db.Index("ix_status_range", "start_date", "end_date"),
    )

    def __repr__(self):
        return f"<StatusEntry {self.id} p{self.person_id} {self.type.value}>"
