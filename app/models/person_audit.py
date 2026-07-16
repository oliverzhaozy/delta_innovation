from app.domain.dates import now_sgt
from app.extensions import db


class PersonAudit(db.Model):
    """Append-only trail of edits to a person's roster fields (ledger posture):
    no update or delete path exists for this model. One row per changed field
    per save, written in the SAME transaction as the person edit, so the trail
    cannot diverge from what was committed. Values are stored as the display
    strings shown in the edit form (enum -> .value, bool -> yes/no, int -> str,
    unset -> SQL NULL) so the view renders them without re-deriving formats.
    """

    __tablename__ = "person_audit"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False, index=True)
    field = db.Column(db.String(40), nullable=False)
    old = db.Column(db.String(120), nullable=True)
    new = db.Column(db.String(120), nullable=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    person = db.relationship("Person", foreign_keys=[person_id])
    actor = db.relationship("Person", foreign_keys=[actor_id])

    def __repr__(self):
        return f"<PersonAudit {self.id} p{self.person_id} {self.field} {self.old!r}->{self.new!r}>"
