from app.domain.dates import now_sgt
from app.extensions import db


class OverseasDeclaration(db.Model):
    """Self-declared travel window; everyone declares, no ledger involved.

    Rows are never deleted — retract sets cancelled_at so the trace survives
    for P6 manning, which reads these rows for activation-standby risk.
    """

    __tablename__ = "overseas_declaration"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)
    cancelled_at = db.Column(db.DateTime)

    person = db.relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        db.CheckConstraint("start_date <= end_date", name="ck_overseas_date_order"),
    )

    @property
    def when_label(self) -> str:
        if self.start_date == self.end_date:
            return self.start_date.strftime("%a %d %b")
        return f"{self.start_date.strftime('%d %b')} – {self.end_date.strftime('%d %b')}"

    def __repr__(self):
        return f"<OverseasDeclaration {self.id} p{self.person_id} {self.destination}>"
