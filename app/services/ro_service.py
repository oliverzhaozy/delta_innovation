"""RO orchestration (P5.4): fetch/shape live rows into the pure domain/ro
render, own the fetch-or-create of the daily keyed slice, and resolve A9's
edit rights.

Everything derivable is derived at render — duty names (CONFIRMED rows dated
the RO's date only), TP lines, and the covering week's key events (from the
TP calendar, 2026-07-24 revision). Only the daily keyed slice (messages blob
+ extra items) and the Matters boilerplate are stored; there is no RO
snapshot by design (the pasted WhatsApp message is the archival record).
"""
from datetime import datetime, time, timedelta

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.domain import policy, ro
from app.domain.types import Calendar, Duty, TpLabel
from app.extensions import db
from app.models import (
    DutyAssignment,
    Event,
    PublicHoliday,
    RoBoilerplate,
    RoDocument,
    RoExtraItem,
)
from app.services import duty_service


def week_start(day):
    """The Monday of `day`'s week — the weekly_key_events key rule."""
    return day - timedelta(days=day.weekday())


def fetch_or_create(day) -> RoDocument:
    """The day's keyed slice, created empty on first touch. The UNIQUE(date)
    constraint is the race guard: a concurrent create loses cleanly and we
    re-read the winner (never SELECT-then-trust)."""
    doc = db.session.query(RoDocument).filter_by(date=day).first()
    if doc is not None:
        return doc
    doc = RoDocument(date=day, messages="")
    db.session.add(doc)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        doc = db.session.query(RoDocument).filter_by(date=day).one()
    return doc


def can_edit_ro_for(person, day) -> bool:
    """A9: editing the RO dated D requires the CDOS of D or D−1 (the
    compiling evening — same reasoning as P4.8's two-day COS window), with
    the command team as fallback. policy.can_edit_ro stays pure; the duty
    fact is resolved here.

    Decision (p): the fallback is deliberately WIDE — every CDO/S-eligible
    appointment is command team, so the duty window is currently subsumed by
    the fallback. The window plumbing stays in case the rule narrows."""
    is_cdos = (
        db.session.query(DutyAssignment.id)
        .filter(
            DutyAssignment.person_id == person.id,
            DutyAssignment.duty == Duty.CDOS,
            DutyAssignment.date.in_((day, day - timedelta(days=1))),
        )
        .first()
        is not None
    )
    return policy.can_edit_ro(person, is_cdos_of_day=is_cdos)


def _duty_name(person):
    """'RANK FULL NAME' in caps (decision m), or None for the placeholder."""
    if person is None:
        return None
    return f"{person.rank.value} {person.display_name.upper()}"


def build(day) -> ro.RoDoc:
    """Assemble one date's RO through the pure renderer. One fetch per input
    kind, all shaped here — routes render `.text` and surface
    `.missing_duties` as chrome, never re-deriving either."""
    doc = fetch_or_create(day)
    monday = week_start(day)
    holiday_names = PublicHoliday.names_between(monday, monday + timedelta(days=4))
    # One fetch covers both consumers: the timeline keeps only events STARTING
    # on `day`, the key-events block any event overlapping a Mon–Fri weekday.
    # The Mon–Sun span contains `day` by construction (monday = week_start(day)).
    # Filtering here is therefore the single site that keeps a rule out of the
    # WHOLE document — domain/ro knows nothing of calendars or labels.
    monday_dt = datetime.combine(monday, time.min)
    tp_events = (
        db.session.query(Event)
        .filter(
            Event.calendar == Calendar.TP,
            # Course conducts never enter the RO (owner, 2026-07-28) — their
            # effect is the participants' absence (presence pipeline), not a
            # company activity. NULL-safe: bare `!=` would drop unlabeled events.
            or_(Event.label.is_(None), Event.label != TpLabel.ON_COURSE.value),
            Event.start_dt < monday_dt + timedelta(days=7),
            Event.end_dt >= monday_dt,
        )
        .order_by(Event.start_dt)
        .all()
    )
    boilerplate = {
        row.section: row.content for row in db.session.query(RoBoilerplate).all()
    }
    key_events = ro.weekly_key_events(
        monday, tp_events=tp_events, holiday_names=holiday_names
    )
    items = ro.timeline_items(day, tp_events=tp_events, extra_items=doc.extra_items)
    return ro.render(
        day,
        cos=_duty_name(duty_service.cos_of_day(day)),
        cdos=_duty_name(duty_service.cdos_of_day(day)),
        items=items,
        boilerplate=boilerplate,
        messages=doc.messages,
        key_events=key_events,
    )


def set_messages(doc, text):
    doc.messages = text
    db.session.commit()


def add_extra_item(doc, *, time_, text) -> RoExtraItem:
    item = RoExtraItem(ro_document_id=doc.id, time=time_, text=text)
    db.session.add(item)
    db.session.commit()
    return item


def remove_extra_item(item_id) -> bool:
    item = db.session.get(RoExtraItem, item_id)
    if item is None:
        return False
    db.session.delete(item)
    db.session.commit()
    return True


def set_boilerplate(section, content) -> RoBoilerplate:
    row = db.session.query(RoBoilerplate).filter_by(section=section).first()
    if row is None:
        row = RoBoilerplate(section=section, content=content)
        db.session.add(row)
    else:
        row.content = content
    db.session.commit()
    return row
