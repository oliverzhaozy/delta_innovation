"""Duty roster orchestration (P4.4): shape DB rows into the pure P4.2/P4.3
inputs, write PROPOSED rosters, confirm behind a content fingerprint.

The pure modules are the law (eligibility.py is frozen per addendum B4;
roster.py is deterministic and solver-free); this module only fetches and
shapes. Availability reads the SAME shared absence fetch as the away board and
every parade document (presence_service.fetch_absence_rows) — a third fetch
path is the drift bug this app exists to kill.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from app.domain import eligibility
from app.domain.types import Calendar, Duty, DutyState
from app.extensions import db
from app.models import DutyAssignment, Event
from app.services import event_service, presence_service


class RosterChanged(Exception):
    """The month's PROPOSED roster changed between page load and confirm (A4);
    message is user-facing."""


def month_bounds(month: str):
    """'YYYY-MM' -> (first day, last day). ValueError on anything else."""
    year_s, mon_s = month.split("-")
    year, mon = int(year_s), int(mon_s)
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


def _assignments_between(first, last, *, state=None):
    query = db.session.query(DutyAssignment).filter(
        DutyAssignment.date >= first, DutyAssignment.date <= last
    )
    if state is not None:
        query = query.filter(DutyAssignment.state == state)
    return query.order_by(DutyAssignment.date, DutyAssignment.duty).all()


def availability_for_month(month: str):
    """(pools, availability, confirmed_rows) for the month — the shaped inputs
    the generator and the manual-assign checks (P4.6) both consume.

    One shared absence fetch for the whole month; in-camp statuses do NOT
    block (in camp is not away — a briefing eats meals and can hold a duty).
    Only OVERNIGHT TP events block (P4.2's stated v1 definition); ARCTIC rows
    are contingency plans, not scheduled conducts, and never block.
    """
    first, last = month_bounds(month)
    people = event_service.active_roster()
    pools = {duty: eligibility.pool(duty, people) for duty in Duty}

    leaves, directs, statuses = presence_service.fetch_absence_rows(first, last)
    absence_rows = defaultdict(list)
    for row in leaves:
        absence_rows[row.person_id].append(row)
    for row in directs:
        absence_rows[row.person_id].append(row)
    for row in statuses:
        if not row.in_camp:
            absence_rows[row.person_id].append(row)

    overnight = defaultdict(list)
    window_start = datetime.combine(first, time.min)
    window_end = datetime.combine(last + timedelta(days=1), time.min)
    events = (
        db.session.query(Event)
        .filter(
            Event.calendar == Calendar.TP,
            Event.start_dt < window_end,
            Event.end_dt > window_start,
        )
        .all()
    )
    for ev in events:
        if ev.end_dt.date() > ev.start_dt.date():
            for p in event_service.resolve_participants(ev):
                overnight[p.id].append(ev)

    confirmed = _assignments_between(first, last, state=DutyState.CONFIRMED)
    held_dates = defaultdict(set)
    for row in confirmed:
        held_dates[row.person_id].add(row.date)

    def availability(person, day):
        return eligibility.available(
            person,
            day,
            absence_rows=absence_rows.get(person.id, ()),
            overnight_events=overnight.get(person.id, ()),
            other_duty_dates=held_dates.get(person.id, frozenset()),
        )

    return pools, availability, confirmed
