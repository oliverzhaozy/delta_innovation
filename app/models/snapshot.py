from app.domain.dates import now_sgt
from app.domain.types import ParadeVariant
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class ParadeSnapshot(db.Model):
    """Append-only freeze of a rendered parade document at copy time.

    NO unique(date, variant) constraint, and no update/delete function or
    route anywhere for this model — re-finalizing before sending is a
    legitimate correction, and the resulting second row IS the audit trail
    (ledger posture: history, never edits). Without this, a live-recomputed
    document would silently change when history changes after the fact
    (TECH_PLAN "Retroactive drift") — the snapshot is what makes "what was
    actually sent" a fixed, checkable fact.
    """

    __tablename__ = "parade_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    variant = db.Column(
        db.Enum(ParadeVariant, values_callable=_values, name="parade_variant"), nullable=False
    )
    rendered_text = db.Column(db.Text, nullable=False)
    finalized_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    finalized_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    finalized_by = db.relationship("Person", foreign_keys=[finalized_by_id])

    def __repr__(self):
        return f"<ParadeSnapshot {self.id} {self.date} {self.variant.value}>"
