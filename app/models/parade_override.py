from app.domain.dates import now_sgt
from app.domain.types import OverrideCategory, ParadeVariant
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class ParadeOverride(db.Model):
    """A keyer's drag-and-drop recategorization of ONE person on ONE parade
    document (P8.2). It moves the rendered line only — no leave/status/ledger
    data is touched; the presence engine still resolves the person, and
    build_doc applies this override on top of that resolution.

    Latest-wins per (date, variant, person): a second drag of the same person
    on the same document overwrites the target via a single-statement SQLite
    upsert on `uq_parade_override_slot`, so there is never a check-then-act
    race. A stored override for a person no longer in the document is inert —
    apply_overrides skips it — so stale rows self-heal without a cleanup job.
    """

    __tablename__ = "parade_override"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    variant = db.Column(
        db.Enum(ParadeVariant, values_callable=_values, name="parade_variant"),
        nullable=False,
    )
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    target_category = db.Column(
        db.Enum(OverrideCategory, values_callable=_values, name="override_category"),
        nullable=False,
    )
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    __table_args__ = (
        db.UniqueConstraint("date", "variant", "person_id", name="uq_parade_override_slot"),
    )

    person = db.relationship("Person", foreign_keys=[person_id])
    created_by = db.relationship("Person", foreign_keys=[created_by_id])

    def __repr__(self):
        return (
            f"<ParadeOverride {self.id} {self.date} {self.variant.value} "
            f"person={self.person_id} -> {self.target_category.value}>"
        )
