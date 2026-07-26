"""DB-aware glue joining the roster onto the pure P2.3 resolver."""
from datetime import datetime, time, timedelta

from app.domain import clash, parade, participants
from app.domain.types import Calendar, ParticipantCategory
from app.extensions import db
from app.models import Event, Person


def active_roster():
    """Active people in PARADE order — appointment, then rank, then platoon,
    then keyed order (owner directive 2026-07-26: every user-facing list of
    people reads the same order the documents print, never alphabetical).
    Neither appointment nor rank seniority is expressible as a column ORDER BY
    (the stored enum values sort by neither), so the one canonical key does it
    in Python; at ~40 rows this costs nothing. Every roster-derived list —
    pickers, pools, candidates, dropdowns — inherits from here.
    """
    people = db.session.query(Person).filter_by(is_active=True).all()
    people.sort(key=parade.parade_sort_key)
    return people


_PICKER_CATEGORIES = (
    ParticipantCategory.NSF,
    ParticipantCategory.REGULAR,
    ParticipantCategory.PLATOON_1,
    ParticipantCategory.PLATOON_2,
    ParticipantCategory.PLATOON_3,
)


def picker_groups():
    """The five grouped picker dropdowns (NSF, REGULAR, PLATOON_1..3) as
    `[(category, [Person, ...]), ...]`. Reuses the two pure functions rather
    than re-deriving membership or order here: `participants.in_category` for
    who's in the group and `parade.parade_sort_key` for the display order —
    appointment then rank, never alphabetical (the owner's parade rule).
    """
    roster = active_roster()
    return [
        (
            category,
            sorted(
                (p for p in roster if participants.in_category(p, category)),
                key=parade.parade_sort_key,
            ),
        )
        for category in _PICKER_CATEGORIES
    ]


def command_person_ids() -> set:
    """Ids of the command team (an appointment-based set) among the active
    roster. The picker marks these person checkboxes so the "Command team"
    category box and its members stay in sync both ways — reuses the pure
    `participants.in_category` predicate rather than re-deriving the appointment
    set here.
    """
    return {
        p.id
        for p in active_roster()
        if participants.in_category(p, ParticipantCategory.COMMAND_TEAM)
    }


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
