from app.domain.dates import now_sgt
from app.domain.types import ParadeVariant
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class ParadeSnapshot(db.Model):
    """Append-only archive of a parade document exactly as it was copied to
    WhatsApp (re-introduced 2026-07-24; a P3a.8 table of the same name was
    dropped 2026-07-11). A row is written when a viewer hits Copy: the server
    re-renders through build_doc and stores THAT text, so the archive is what
    was actually sent, never client-supplied. No update/delete path exists — a
    changed document appends a new row; parade_service.save_snapshot skips the
    insert only when the newest row for this (date, variant) is byte-identical.
    """

    __tablename__ = "parade_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    variant = db.Column(
        db.Enum(ParadeVariant, values_callable=_values, name="parade_variant"),
        nullable=False,
    )
    rendered_text = db.Column(db.Text, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    created_by = db.relationship("Person", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<ParadeSnapshot {self.id} {self.date} {self.variant.value}>"
