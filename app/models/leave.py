from app.domain.dates import now_sgt
from app.domain.types import DayPart, LeaveType, RequestStatus
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class LeaveRequest(db.Model):
    """One request per date range. Absences are DERIVED from APPROVED rows —
    there is no separate stored calendar to drift out of sync.
    """

    __tablename__ = "leave_request"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False, index=True)
    type = db.Column(db.Enum(LeaveType, values_callable=_values, name="leave_type"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    day_part = db.Column(
        db.Enum(DayPart, values_callable=_values, name="day_part"),
        nullable=False,
        default=DayPart.FULL,
    )
    reason = db.Column(db.String(300))
    status = db.Column(
        db.Enum(RequestStatus, values_callable=_values, name="request_status"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)
    pc_actor_id = db.Column(db.Integer, db.ForeignKey("person.id"))
    pc_at = db.Column(db.DateTime)
    oc_actor_id = db.Column(db.Integer, db.ForeignKey("person.id"))
    oc_at = db.Column(db.DateTime)
    remarks = db.Column(db.String(300))  # approver remark (rejections, overrides)

    person = db.relationship("Person", foreign_keys=[person_id])
    pc_actor = db.relationship("Person", foreign_keys=[pc_actor_id])
    oc_actor = db.relationship("Person", foreign_keys=[oc_actor_id])

    __table_args__ = (
        db.CheckConstraint("start_date <= end_date", name="ck_leave_date_order"),
        # Half-day only makes sense for a single day (TECH_PLAN assumption 3).
        db.CheckConstraint(
            "day_part = 'FULL' OR start_date = end_date", name="ck_leave_half_day_single_day"
        ),
        db.Index("ix_leave_range", "start_date", "end_date"),
    )

    @property
    def when_label(self) -> str:
        if self.start_date == self.end_date:
            day = self.start_date.strftime("%a %d %b")
            return day if self.day_part is DayPart.FULL else f"{day} ({self.day_part.value})"
        return f"{self.start_date.strftime('%d %b')} – {self.end_date.strftime('%d %b')}"

    def __repr__(self):
        return f"<LeaveRequest {self.id} p{self.person_id} {self.type.value} {self.status.value}>"
