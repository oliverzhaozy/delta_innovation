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
from collections import defaultdict, namedtuple
from datetime import date, datetime, time, timedelta

from sqlalchemy import update

from app.domain import eligibility, policy, presence, roster
from app.domain.dates import iter_days, now_sgt, today_sgt
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
    block (in camp is not away — an in-camp status eats meals and can hold a duty).
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


class IneligibleAssignment(Exception):
    """Rule violation (a PC can never hold COS) — hard block, 4xx, never a warning."""


class NeedsAvailabilityConfirm(Exception):
    """Soft problems (decision d: the PS may assign over them with an explicit
    confirm). `reasons` is the user-facing list."""

    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _availability_reasons(person, day, duty):
    """Soft-warning reasons for putting `person` on (day, duty): covering
    absence/overnight event, adjacency (incl. cross-month tail), spread breach.
    """
    month = day.strftime("%Y-%m")
    pools, availability, _confirmed = availability_for_month(month)
    reasons = []
    if not availability(person, day):
        reasons.append("covering absence, overnight TP event, or duty that day")
    first, last = month_bounds(month)
    rows = _assignments_between(first, last)
    _counts, tail = _prior_month_inputs(first)
    held = {r.date for r in rows if r.person_id == person.id and r.date != day}
    held.update(d for d, _duty, person_id in tail if person_id == person.id)
    if any(roster.adjacent_duty_days(day, other) for other in held):
        reasons.append("adjacent duty day (incl. Fri→Mon)")
    counts = {p.id: 0 for p in pools[duty]}
    for r in rows:
        if r.duty is duty and r.person_id in counts and r.date != day:
            counts[r.person_id] += 1
    if person.id in counts:
        counts[person.id] += 1
        if max(counts.values()) - min(counts.values()) > 1:
            reasons.append(f"would breach {duty.label} spread (max−min > 1)")
    return reasons


def assign(day, duty, person, *, actor, override_availability):
    """Assign/replace one (date, duty). Eligibility is LAW (hard block);
    availability/adjacency/spread are judgment (warn-then-confirm). Replacing a
    CONFIRMED row keeps it CONFIRMED with a fresh confirm stamp — manual replace
    is exactly how the PS resolves a post-approval clash; a new row on an empty
    slot is PROPOSED (it becomes real only when the month is confirmed)."""
    rule = eligibility.eligible_cos if duty is Duty.COS else eligibility.eligible_cdos
    if not (person.is_active and rule(person)):
        raise IneligibleAssignment(
            f"{person.display_name} can never hold {duty.label} — rank/appointment rule."
        )
    if person.duty_exempt:
        raise IneligibleAssignment(
            f"{person.display_name} is exempt from duty — clear the exemption "
            "in Admin → People first."
        )
    reasons = _availability_reasons(person, day, duty)
    if reasons and not override_availability:
        raise NeedsAvailabilityConfirm(reasons)
    row = (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day, DutyAssignment.duty == duty)
        .first()
    )
    if row is None:
        row = DutyAssignment(
            date=day, duty=duty, person_id=person.id,
            state=DutyState.PROPOSED, created_by_id=actor.id,
        )
        db.session.add(row)
    else:
        row.person_id = person.id
        if row.state is DutyState.CONFIRMED:
            row.confirmed_by_id = actor.id
            row.confirmed_at = now_sgt()
    db.session.commit()
    return row


def clear(day, duty) -> bool:
    row = (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day, DutyAssignment.duty == duty)
        .first()
    )
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def confirmed_on(day):
    """CONFIRMED assignments dated `day` — the consumers' notice helper (A7):
    when a night has no confirmed duty (rollout ramp, month boundary), pages
    say so in chrome; the document text never changes."""
    return (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day, DutyAssignment.state == DutyState.CONFIRMED)
        .order_by(DutyAssignment.duty)
        .all()
    )


def _confirmed_holder(day, duty):
    row = (
        db.session.query(DutyAssignment)
        .filter(
            DutyAssignment.date == day,
            DutyAssignment.duty == duty,
            DutyAssignment.state == DutyState.CONFIRMED,
        )
        .first()
    )
    return row.person if row is not None else None


def cos_of_day(day):
    """CONFIRMED COS holder for `day`, or None (autofills the greeting)."""
    return _confirmed_holder(day, Duty.COS)


def cdos_of_day(day):
    """CONFIRMED CDO/S holder for `day`, or None — P5's RO-rights input."""
    return _confirmed_holder(day, Duty.CDOS)


def can_key_parade_today(person) -> bool:
    """The DB-aware wrapper every route and template calls: PS/S3/admin
    fallback OR CONFIRMED COS for today or tomorrow (tomorrow's COS compiles
    day-D's message on the evening of D−1 — assumption 4 makes the two-day
    window the honest one). One duty query per page render — accepted at 40
    users (A5); do not add caching. Rights are date-independent: the window
    decides WHO can key, not WHICH dates they may key."""
    today = today_sgt()
    is_cos = (
        db.session.query(DutyAssignment.id)
        .filter(
            DutyAssignment.person_id == person.id,
            DutyAssignment.duty == Duty.COS,
            DutyAssignment.state == DutyState.CONFIRMED,
            DutyAssignment.date.in_((today, today + timedelta(days=1))),
        )
        .first()
        is not None
    )
    return policy.can_key_parade(person, is_cos_of_day=is_cos)


def _absent_assignment_ids(rows, first, last):
    """Assignment ids whose CONFIRMED holder resolves ABSENT on the duty date,
    derived from the shared fetch (A8): an MC, a direct absence, and approved
    leave all flag the same way, because the predicate IS presence, not a
    leave-table join. Never stored — recomputed at render."""
    confirmed = [r for r in rows if r.state is DutyState.CONFIRMED]
    if not confirmed:
        return frozenset()
    leaves, directs, statuses = presence_service.fetch_absence_rows(first, last)
    by_person = defaultdict(lambda: ([], [], []))
    for row in leaves:
        by_person[row.person_id][0].append(row)
    for row in directs:
        by_person[row.person_id][1].append(row)
    for row in statuses:
        by_person[row.person_id][2].append(row)
    flagged = set()
    for r in confirmed:
        p_leaves, p_directs, p_statuses = by_person.get(r.person_id, ((), (), ()))
        resolution = presence.resolve(
            r.person, r.date,
            leaves=p_leaves, direct_absences=p_directs, statuses=p_statuses,
        )
        if resolution.state is presence.PresenceState.ABSENT:
            flagged.add(r.id)
    return frozenset(flagged)


MonthView = namedtuple(
    "MonthView", "first last days rows by_slot pools violations fingerprint absent_flags"
)


def month_view(month: str) -> MonthView:
    """Everything the roster page renders, assembled once. `violations` and
    `absent_flags` are re-derived from the CURRENT rows on every call (the pure
    module's contract: re-flag after manual edits, not only after generation).
    Blanks are slots with NO row — the DB never stores a None assignment."""
    first, last = month_bounds(month)
    days = list(iter_days(first, last))
    rows = _assignments_between(first, last)
    by_slot = {(r.date, r.duty): r for r in rows}
    people = event_service.active_roster()
    pools = {duty: eligibility.pool(duty, people) for duty in Duty}
    assignments = {
        (d, duty): (by_slot[(d, duty)].person_id if (d, duty) in by_slot else None)
        for d in days
        for duty in Duty
    }
    _counts, prior_tail = _prior_month_inputs(first)
    return MonthView(
        first=first, last=last, days=days, rows=rows, by_slot=by_slot,
        pools=pools,
        violations=roster.violations(assignments, pools, prior_tail=prior_tail),
        fingerprint=roster_fingerprint(month),
        absent_flags=_absent_assignment_ids(rows, first, last),
    )


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
