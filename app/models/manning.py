"""TU manning storage (P6.2) — a period and its slot assignments. Conflicts
are never stored (A8: derived at render from the shared fetch + overseas
declarations); there is no manning snapshot by design (the pasted list is the
record).
"""
from app.domain.dates import now_sgt
from app.domain.types import ManningSlotType
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class ManningPeriod(db.Model):
    """One activation-standby window, identified by its dates alone (owner
    2026-07-28). Date-ranged in the document (usually 4–7 days, advisory —
    never validated)."""

    __tablename__ = "manning_period"

    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    created_by = db.relationship("Person", foreign_keys=[created_by_id])
    slots = db.relationship(
        "ManningSlot", cascade="all, delete-orphan", back_populates="period",
        order_by="ManningSlot.id",
    )

    __table_args__ = (
        db.CheckConstraint("start_date <= end_date", name="ck_manning_date_order"),
    )

    def __repr__(self):
        return f"<ManningPeriod {self.id} {self.start_date}–{self.end_date}>"


class ManningSlot(db.Model):
    """One filled slot. det_number groups a TU Det Comd with their personnel
    (NULL for the HQ slots TU_COMD/TU_PLANNER — the CHECK pins that shape);
    UNIQUE(period_id, person_id) is the one-slot-per-person backstop.

    `is_manual` marks the S3's own pick: regeneration replaces only the
    generator's rows (`is_manual=False`) and leaves manual ones standing."""

    __tablename__ = "manning_slot"

    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(
        db.Integer, db.ForeignKey("manning_period.id"), nullable=False, index=True
    )
    slot = db.Column(
        db.Enum(ManningSlotType, values_callable=_values, name="manning_slot_type"),
        nullable=False,
    )
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    det_number = db.Column(db.Integer, nullable=True)

    period = db.relationship("ManningPeriod", back_populates="slots")
    person = db.relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        db.UniqueConstraint("period_id", "person_id", name="uq_manning_person_once"),
        db.CheckConstraint(
            "(slot IN ('TU_DET_COMD', 'DET_PERSONNEL')) = (det_number IS NOT NULL)",
            name="ck_manning_det_number_shape",
        ),
    )

    def __repr__(self):
        return f"<ManningSlot {self.slot.value} p{self.person_id} det={self.det_number}>"
