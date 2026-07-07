"""Duty roster orchestration (P4.4): shape DB rows into the pure P4.2/P4.3
inputs, write PROPOSED rosters, confirm behind a content fingerprint.

The pure modules are the law (eligibility.py is frozen per addendum B4;
roster.py is deterministic and solver-free); this module only fetches and
shapes. Availability reads the SAME shared absence fetch as the away board and
every parade document (presence_service.fetch_absence_rows) — a third fetch
path is the drift bug this app exists to kill.
"""
import hashlib
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import update

from app.domain import eligibility, roster
from app.domain.dates import iter_days, now_sgt
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


def _prior_month_inputs(first):
    """CONFIRMED-only history for the generator (A7): counts = the whole
    previous month; tail = its last 3 calendar days (Fri->Mon adjacency can
    reach 3 days back). Both empty when no previous month exists — an empty
    tail means no adjacency constraint from the past, defined, not crashed."""
    prev_last = first - timedelta(days=1)
    prev_first = prev_last.replace(day=1)
    rows = _assignments_between(prev_first, prev_last, state=DutyState.CONFIRMED)
    prior_counts = {duty: defaultdict(int) for duty in Duty}
    for row in rows:
        prior_counts[row.duty][row.person_id] += 1
    tail_start = prev_last - timedelta(days=2)
    prior_tail = [(r.date, r.duty, r.person_id) for r in rows if r.date >= tail_start]
    return prior_counts, prior_tail


def generate_month(month: str, actor):
    """Generate the month's PROPOSED roster in one transaction, replacing only
    PROPOSED rows — CONFIRMED rows are never touched by regeneration.

    One generate() call PER DUTY over that duty's open (non-CONFIRMED) days:
    the appointment pools are disjoint, so per-duty runs cannot double-book a
    person, and skipping confirmed slots this way keeps the pure module's
    internal counts honest (no discarded picks). In-month CONFIRMED rows join
    the tail (adjacency must see them) and the prior counts (evenness bias).
    """
    first, last = month_bounds(month)
    pools, availability, confirmed = availability_for_month(month)
    prior_counts, prior_tail = _prior_month_inputs(first)

    confirmed_slots = {(r.date, r.duty) for r in confirmed}
    tail = list(prior_tail) + [(r.date, r.duty, r.person_id) for r in confirmed]
    counts = {duty: dict(prior_counts[duty]) for duty in Duty}
    for r in confirmed:
        counts[r.duty][r.person_id] = counts[r.duty].get(r.person_id, 0) + 1

    all_days = list(iter_days(first, last))
    picks = {}
    for duty in Duty:
        open_days = [d for d in all_days if (d, duty) not in confirmed_slots]
        picks.update(
            roster.generate(
                open_days, {duty: pools[duty]}, availability,
                prior_counts=counts, prior_tail=tail,
            )
        )

    db.session.query(DutyAssignment).filter(
        DutyAssignment.date >= first,
        DutyAssignment.date <= last,
        DutyAssignment.state == DutyState.PROPOSED,
    ).delete()
    for (day, duty), person_id in picks.items():
        if person_id is None:
            continue  # blank day: no row — the page derives blanks (P4.5)
        db.session.add(
            DutyAssignment(
                date=day, duty=duty, person_id=person_id,
                state=DutyState.PROPOSED, created_by_id=actor.id,
            )
        )
    db.session.commit()


def roster_fingerprint(month: str) -> str:
    """sha256 over the sorted (date, duty, person_id) CONTENT of the month's
    PROPOSED rows (A4). Content-based on purpose: an UPDATE-in-place regenerate
    and a single manual edit both change it; count+max(id) would not."""
    first, last = month_bounds(month)
    rows = _assignments_between(first, last, state=DutyState.PROPOSED)
    canon = "|".join(
        f"{r.date.isoformat()},{r.duty.value},{r.person_id}"
        for r in sorted(rows, key=lambda r: (r.date, r.duty.value, r.person_id))
    )
    return hashlib.sha256(canon.encode()).hexdigest()


def confirm_month(month: str, actor, fingerprint: str):
    """Confirm the month's PROPOSED rows — but only the roster the actor
    actually reviewed: the posted fingerprint is recomputed inside this
    transaction and a mismatch aborts (A4 — the plain WHERE state='PROPOSED'
    claim would confirm whatever PS B regenerated after PS A loaded the page).
    """
    first, last = month_bounds(month)
    if roster_fingerprint(month) != fingerprint:
        db.session.rollback()
        raise RosterChanged(
            "Roster changed since you loaded this page — re-review before confirming."
        )
    db.session.execute(
        update(DutyAssignment)
        .where(
            DutyAssignment.date >= first,
            DutyAssignment.date <= last,
            DutyAssignment.state == DutyState.PROPOSED,
        )
        .values(
            state=DutyState.CONFIRMED,
            confirmed_by_id=actor.id,
            confirmed_at=now_sgt(),
        )
    )
    db.session.commit()
