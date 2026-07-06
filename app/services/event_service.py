"""DB-aware glue joining the roster onto the pure P2.3 resolver."""
from datetime import datetime, time, timedelta

from app.domain import clash, participants
from app.domain.types import RANK_ORDER, Calendar
from app.extensions import db
from app.models import Event, Person


def active_roster():
    """Active people, ordered platoon -> rank (seniority) -> name — the
    deterministic ordering TECH_PLAN specifies for every roster-derived list.
    Rank seniority isn't expressible as a plain column ORDER BY (the stored
    enum value doesn't sort in seniority order), so the rank/name tiebreak
    happens in Python via a stable sort over the already platoon+name
    ordered query; at ~40 rows this costs nothing.
    """
    people = (
        db.session.query(Person)
        .filter_by(is_active=True)
        .order_by(Person.platoon.nulls_first(), Person.display_name)
        .all()
    )
    return sorted(
        people,
        key=lambda p: (p.platoon if p.platoon is not None else -1, -RANK_ORDER[p.rank]),
    )


def resolve_participants(event) -> list:
    """Resolve `event`'s category/person rows against who's active right now
    — categories are never stored membership, they resolve at query time.
    """
    return participants.resolve(event.participants, active_roster())


def clashes_for(leave_request, *, include_arctic):
    """Events overlapping `leave_request`'s window that the requester is
    actually tagged in, ordered by start.

    Three-stage refinement keeps each stage cheap and reuses already-tested
    logic rather than re-deriving it here:
      1. Coarse SQL range query on `ix_event_range` — a full-day envelope
         around the request, so no row that could possibly overlap is missed.
      2. The pure P2.7 `leave_clashes_with_event` for the exact day-part
         window (the 12:00 boundary lives there, not here).
      3. P2.5's `resolve_participants` to keep only events the requester is
         actually tagged in (category or person row).
    """
    envelope_start = datetime.combine(leave_request.start_date, time.min)
    envelope_end = datetime.combine(leave_request.end_date + timedelta(days=1), time.min)
    query = db.session.query(Event).filter(
        Event.start_dt < envelope_end,
        Event.end_dt > envelope_start,
    )
    if not include_arctic:
        # ARCTIC visibility follows the viewer, not the requester — a
        # non-command requester must never learn of ARCTIC events via leave.
        query = query.filter(Event.calendar != Calendar.ARCTIC)
    candidates = query.order_by(Event.start_dt).all()

    result = []
    for event in candidates:
        if not clash.leave_clashes_with_event(
            leave_request.start_date,
            leave_request.end_date,
            leave_request.day_part,
            event.start_dt,
            event.end_dt,
        ):
            continue
        participant_ids = {p.id for p in resolve_participants(event)}
        if leave_request.person_id not in participant_ids:
            continue
        result.append(event)
    return result
