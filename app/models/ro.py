"""RO (Routine Orders) storage — P5.2, shaped by docs/RO_FORMATS.md decisions:

- Standing text is data, not code: the six Matters sections (ro_boilerplate)
  and the recurring timeline items (ro_standing_item) are S3-edited rows, so
  an "otherwise stated" week is an edit, not a release.
- ro_document is the DAILY keyed part only (one pasted messages/QOTD blob);
  duty names, TP lines, and standing items are derived at render — storing
  them would be the calendar-drift bug this app exists to kill.
- No RO snapshot table by design: the pasted WhatsApp message is the archival
  record (TECH_PLAN, deliberately cut from P5).
"""
from app.domain.types import RoRecurrence, RoSection
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


class RoStandingItem(db.Model):
    """A recurring timeline line (decision (n)): seeded with 0600H roll call +
    TBC LP daily and TBC SBA on the last working day; S3 edits cover the rest.
    `position` orders items within the same time slot (SBA before LP)."""

    __tablename__ = "ro_standing_item"

    id = db.Column(db.Integer, primary_key=True)
    time = db.Column(db.Time, nullable=True)
    text = db.Column(db.String(200), nullable=False)
    recurrence = db.Column(
        db.Enum(RoRecurrence, values_callable=_values, name="ro_recurrence"),
        nullable=False,
    )
    position = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f"<RoStandingItem {self.text!r} {self.recurrence.value}>"


class WeeklyKeyEvents(db.Model):
    """The Mon–Fri key-events block for one week; `week_start` is normalized
    to the Monday server-side (the service owns that rule)."""

    __tablename__ = "weekly_key_events"

    id = db.Column(db.Integer, primary_key=True)
    week_start = db.Column(db.Date, nullable=False, unique=True)
    mon = db.Column(db.String(300), nullable=False, default="")
    tue = db.Column(db.String(300), nullable=False, default="")
    wed = db.Column(db.String(300), nullable=False, default="")
    thu = db.Column(db.String(300), nullable=False, default="")
    fri = db.Column(db.String(300), nullable=False, default="")

    def __repr__(self):
        return f"<WeeklyKeyEvents {self.week_start}>"
