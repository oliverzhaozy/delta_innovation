from app.domain.dates import now_sgt, range_label
from app.domain.types import DeclarationStatus
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class OverseasDeclaration(db.Model):
    """Self-declared travel window; everyone declares, no ledger involved.

    Rows ARE deleted (owner directive 2026-07-28, reversing P2.1): retracting
    removes the row outright, and a row whose end_date has passed is deleted on
    the next page load (`overseas_service.purge_expired`) — no travel history is
    kept. Approval is PC-only: PS/Det Comd/Opr declarations start PENDING, a
    PC's own and a regular's start APPROVED (domain.routing). Manning flags
    every non-REJECTED row, pending ones included (domain.manning).
    """

    __tablename__ = "overseas_declaration"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)
    status = db.Column(
        db.Enum(DeclarationStatus, values_callable=_values, name="declaration_status"),
        nullable=False,
        index=True,
    )
    pc_actor_id = db.Column(db.Integer, db.ForeignKey("person.id"))
    pc_at = db.Column(db.DateTime)
    # Legacy display only: rejection carries no remark since 2026-08-02 (owner
    # reversal of part of decision (y)), so nothing writes this column any more —
    # it is kept so rows keyed before that date still render their reason.
    remarks = db.Column(db.String(300))

    person = db.relationship("Person", foreign_keys=[person_id])
    pc_actor = db.relationship("Person", foreign_keys=[pc_actor_id])

    __table_args__ = (
        db.CheckConstraint("start_date <= end_date", name="ck_overseas_date_order"),
    )

    @property
    def when_label(self) -> str:
        if self.start_date == self.end_date:
            return self.start_date.strftime("%a %d %b")
        return range_label(self.start_date, self.end_date)

    def __repr__(self):
        return f"<OverseasDeclaration {self.id} p{self.person_id} {self.destination}>"
