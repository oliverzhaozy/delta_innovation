"""RO (Routine Orders) storage — P5.2, shaped by docs/RO_FORMATS.md decisions
(2026-07-24 revision: standing timeline items and hand-keyed weekly key
events are gone — key events derive from the TP calendar at render):

- Standing text is data, not code: the six Matters sections (ro_boilerplate)
  are S3-edited rows, so an "otherwise stated" week is an edit, not a release.
- ro_document is the DAILY keyed part only (one pasted messages/QOTD blob);
  duty names, TP lines, and key events are derived at render — storing
  them would be the calendar-drift bug this app exists to kill.
- No RO snapshot table by design: the pasted WhatsApp message is the archival
  record (TECH_PLAN, deliberately cut from P5).
"""
from app.domain.types import RoSection
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class RoBoilerplate(db.Model):
    """One row per Matters section; empty content renders the bare dash."""

    __tablename__ = "ro_boilerplate"

    id = db.Column(db.Integer, primary_key=True)
    section = db.Column(
        db.Enum(RoSection, values_callable=_values, name="ro_section"),
        nullable=False,
        unique=True,
    )
    content = db.Column(db.Text, nullable=False, default="")

    def __repr__(self):
        return f"<RoBoilerplate {self.section.value}>"


class RoDocument(db.Model):
    """The daily keyed slice of one RO: the pasted Messages-and-QOTD blob.
    Extra timeline items hang off it; everything else is derived at render."""

    __tablename__ = "ro_document"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    messages = db.Column(db.Text, nullable=False, default="")

    extra_items = db.relationship(
        "RoExtraItem", cascade="all, delete-orphan", back_populates="document",
        order_by="RoExtraItem.id",
    )

    def __repr__(self):
        return f"<RoDocument {self.date}>"


class RoExtraItem(db.Model):
    """One hand-keyed timeline line. `time` None = the TBC block."""

    __tablename__ = "ro_extra_item"

    id = db.Column(db.Integer, primary_key=True)
    ro_document_id = db.Column(
        db.Integer, db.ForeignKey("ro_document.id"), nullable=False, index=True
    )
    time = db.Column(db.Time, nullable=True)
    text = db.Column(db.String(200), nullable=False)

    document = db.relationship("RoDocument", back_populates="extra_items")

    def __repr__(self):
        when = self.time.strftime("%H%M") if self.time else "TBC"
        return f"<RoExtraItem {when} {self.text!r}>"
