from app.domain.events import label_class_for
from app.domain.types import Calendar, ParticipantCategory
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class Event(db.Model):
    """Calendar event (TP/ARCTIC); resolved participant list is derived in P2.3
    from the person/category rows below, not stored here.
    """

    __tablename__ = "event"

    id = db.Column(db.Integer, primary_key=True)
    calendar = db.Column(db.Enum(Calendar, values_callable=_values, name="calendar"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    start_dt = db.Column(db.DateTime, nullable=False)
    end_dt = db.Column(db.DateTime, nullable=False)
    # All-day events store 00:00 → 23:59:59.999999 (see domain.events.all_day_bounds);
    # the flag drives display (date-only, no time) — the times stay valid either way.
    all_day = db.Column(db.Boolean, nullable=False, default=False)
    # The label's VALUE string, validated per-calendar on write (UI-9). Kept as a
    # plain string (not a db.Enum) because the allowed set depends on `calendar`.
    label = db.Column(db.String(40))
    notes = db.Column(db.String(500))
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)

    created_by = db.relationship("Person", foreign_keys=[created_by_id])
    # Participant rows belong to the event; P2.4 hard-deletes events, so their
    # participant rows must go with them rather than being orphaned.
    participants = db.relationship(
        "EventParticipant", cascade="all, delete-orphan", back_populates="event"
    )

    __table_args__ = (
        # Strict: a zero-length event is meaningless.
        db.CheckConstraint("end_dt > start_dt", name="ck_event_dt_order"),
        db.Index("ix_event_range", "start_dt", "end_dt"),
    )

    @property
    def label_enum(self):
        """The TpLabel/ArcticLabel member for `label` (or None) — one place for
        templates to read the label's display text (`.value`) and colour slug
        (`.slug`). Guarded so a legacy/invalid string degrades to None."""
        if not self.label:
            return None
        try:
            return label_class_for(self.calendar)(self.label)
        except ValueError:
            return None

    def __repr__(self):
        return f"<Event {self.id} {self.calendar.value} {self.title!r}>"


class EventParticipant(db.Model):
    """Either a specific person or a whole category (e.g. Platoon 2); `include`
    lets S3 carve out a per-person exception from a category row.
    """

    __tablename__ = "event_participant"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False, index=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=True)
    category = db.Column(
        db.Enum(ParticipantCategory, values_callable=_values, name="participant_category"),
        nullable=True,
    )
    include = db.Column(db.Boolean, nullable=False, default=True)

    event = db.relationship("Event", foreign_keys=[event_id], back_populates="participants")
    person = db.relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        db.CheckConstraint(
            "(person_id IS NULL) != (category IS NULL)", name="ck_participant_person_xor_category"
        ),
        # SQLite treats NULLs as distinct, so these two don't collide across
        # row types (same trick as the ledger's request/source/kind backstop).
        db.UniqueConstraint("event_id", "person_id", name="uq_participant_event_person"),
        db.UniqueConstraint("event_id", "category", name="uq_participant_event_category"),
    )

    def __repr__(self):
        who = f"p{self.person_id}" if self.person_id else self.category.value
        return f"<EventParticipant {self.id} event{self.event_id} {who} include={self.include}>"
