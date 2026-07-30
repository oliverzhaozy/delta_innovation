"""Duty roster orchestration (P4.4): shape DB rows into the pure P4.2/P4.3
inputs and write the month's roster in one transaction.

The pure modules are the law (eligibility.py is frozen per addendum B4;
roster.py is deterministic and solver-free); this module only fetches and
shapes. Availability reads the SAME shared absence fetch as the away board and
every parade document (presence_service.fetch_absence_rows) — a third fetch
path is the drift bug this app exists to kill.

Owner directive 2026-07-27: a written row is live immediately (no draft
state), COS and CDO/S run on working days only, and a blocked day is an
explicit "no duty needed". `duty_days` below owns that day rule for everyone.

Decision (z) 2026-07-28: TP events never block AS EVENTS — this module runs no
event query of its own and passes nothing to `eligibility.available`'s frozen
B4 event parameter, which keeps its empty default for P6.3's use. A
Course-labelled TP event still blocks, but only as a course cover reaching this
module through the shared absence fetch above.

Decision (ee) 2026-07-30: a platoon category may be excused the COS pool. That
carve-out is applied HERE, in `_pools`, because eligibility.py's API is frozen
(B4) and the rule is keyed data, not law — the excused platoon's people are
never auto-picked but stay manually assignable with a warning.
"""
from calendar import monthrange
from collections import defaultdict, namedtuple
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError

from app.domain import eligibility, policy, presence, roster
from app.domain.dates import is_working_day, iter_days, today_sgt
from app.domain.types import Duty
from app.extensions import db
from app.models import DutyAssignment, DutyBlockedDay, PublicHoliday
from app.services import event_service, platoon_service, presence_service


def month_bounds(month: str):
    """'YYYY-MM' -> (first day, last day). ValueError on anything else."""
    year_s, mon_s = month.split("-")
    year, mon = int(year_s), int(mon_s)
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


DutyDays = namedtuple("DutyDays", "weekdays active holidays blocked")


def duty_days(first, last) -> DutyDays:
    """The ONE owner of "which dates carry a duty" (owner 2026-07-27).

    `weekdays` = every Mon-Fri date in range (the grid's rows — weekends are
    not planned and are not shown); `active` = those minus public holidays and
    blocked days (the dates the generator plans and manual assignment accepts);
    `holidays` = {date: name} for the chrome; `blocked` = the blocked dates.
    Generation, the roster page, and manual assignment all call this rather
    than re-deriving the rule.
    """
    holidays = PublicHoliday.names_between(first, last)
    blocked = frozenset(
        row.date
        for row in db.session.query(DutyBlockedDay.date)
        .filter(DutyBlockedDay.date >= first, DutyBlockedDay.date <= last)
        .all()
    )
    holiday_dates = frozenset(holidays)
    weekdays = [d for d in iter_days(first, last) if d.weekday() < 5]
    active = [
        d for d in weekdays if is_working_day(d, holiday_dates) and d not in blocked
    ]
    return DutyDays(weekdays=weekdays, active=active, holidays=holidays, blocked=blocked)


Pools = namedtuple("Pools", "auto assignable")


def _pools(people) -> Pools:
    """The ONE owner of "which pool is which" (decision (ee)).

    `assignable` is the raw eligibility pool — who may LEGALLY hold the duty, and
    therefore what the manual-assign dropdown offers. `auto` is that minus the
    platoons excused the COS pool: who the generator may PICK, what the pools
    panel shows, and what spread violations are measured over. CDO/S is never
    filtered — the toggle is about COS, and a platoon's PS does CDO/S regardless.

    Both call sites (availability_for_month, month_view) come through here so the
    pool the page shows and the pool the generator uses cannot drift apart.
    """
    assignable = {duty: eligibility.pool(duty, people) for duty in Duty}
    excluded = platoon_service.cos_excluded_platoons()
    auto = {
        duty: [
            p for p in members
            if duty is not Duty.COS or p.platoon not in excluded
        ]
        for duty, members in assignable.items()
    }
    return Pools(auto=auto, assignable=assignable)


def _assignments_between(first, last):
    return (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date >= first, DutyAssignment.date <= last)
        .order_by(DutyAssignment.date, DutyAssignment.duty)
        .all()
    )


def availability_for_month(month: str):
    """(pools, availability, manual_rows) for the month — the shaped inputs
    the generator and the manual-assign checks (P4.6) both consume. `pools` is
    the AUTO-PICK pool, so its COS list already excludes the platoons excused
    from that pool (decision (ee)).

    One shared absence fetch for the whole month; in-camp statuses do NOT
    block (in camp is not away — an in-camp status eats meals and can hold a
    duty). Only a covering absence (approved leave/OFF/OIL, an out-of-camp
    status, a course) or already holding the other duty that date skips a
    person. No event query runs here: a TP event blocks nothing AS AN EVENT
    (decision z — a whole-company multi-day conduct left the month ungenerable,
    and its participants are in camp), and the one TP event that still counts,
    an ON COURSE label, arrives above as a course cover. ARCTIC rows never
    blocked and still don't.

    Held-duty dates come from MANUAL rows only: the generator's own rows are
    deleted and re-planned in the same transaction, so counting them would
    make a person look unavailable for the very slot being re-planned.
    """
    first, last = month_bounds(month)
    pools = _pools(event_service.active_roster()).auto

    leaves, statuses, courses = presence_service.fetch_absence_rows(first, last)
    absence_rows = defaultdict(list)
    for row in leaves:
        absence_rows[row.person_id].append(row)
    for row in statuses:
        if not row.in_camp:
            absence_rows[row.person_id].append(row)
    # A course cover is out of camp by construction — it has no in_camp flag to
    # test, and someone on course cannot hold a duty.
    for row in courses:
        absence_rows[row.person_id].append(row)

    manual = [r for r in _assignments_between(first, last) if r.is_manual]
    held_dates = defaultdict(set)
    for row in manual:
        held_dates[row.person_id].add(row.date)

    def availability(person, day):
        return eligibility.available(
            person,
            day,
            absence_rows=absence_rows.get(person.id, ()),
            other_duty_dates=held_dates.get(person.id, frozenset()),
        )

    return pools, availability, manual


def _prior_month_inputs(first):
    """Previous-month history for the generator (A7): counts = the whole
    previous month; tail = its last 3 calendar days (Fri->Mon adjacency can
    reach 3 days back). Every row counts — there are no drafts. Both empty when
    no previous month exists — an empty tail means no adjacency constraint from
    the past, defined, not crashed."""
    prev_last = first - timedelta(days=1)
    prev_first = prev_last.replace(day=1)
    rows = _assignments_between(prev_first, prev_last)
    prior_counts = {duty: defaultdict(int) for duty in Duty}
    for row in rows:
        prior_counts[row.duty][row.person_id] += 1
    tail_start = prev_last - timedelta(days=2)
    prior_tail = [(r.date, r.duty, r.person_id) for r in rows if r.date >= tail_start]
    return prior_counts, prior_tail


def generate_month(month: str, actor):
    """Generate the month's roster in one transaction over its DUTY DAYS,
    replacing only auto-generated rows — a manual pick is never re-planned.

    One generate() call PER DUTY over that duty's open (non-manual) days: the
    appointment pools are disjoint, so per-duty runs cannot double-book a
    person, and skipping manual slots this way keeps the pure module's internal
    counts honest (no discarded picks). In-month manual rows join the tail
    (adjacency must see them) and the prior counts (evenness bias).
    """
    first, last = month_bounds(month)
    pools, availability, manual = availability_for_month(month)
    prior_counts, prior_tail = _prior_month_inputs(first)

    manual_slots = {(r.date, r.duty) for r in manual}
    tail = list(prior_tail) + [(r.date, r.duty, r.person_id) for r in manual]
    counts = {duty: dict(prior_counts[duty]) for duty in Duty}
    for r in manual:
        counts[r.duty][r.person_id] = counts[r.duty].get(r.person_id, 0) + 1

    days = duty_days(first, last).active
    picks = {}
    for duty in Duty:
        open_days = [d for d in days if (d, duty) not in manual_slots]
        picks.update(
            roster.generate(
                open_days, {duty: pools[duty]}, availability,
                prior_counts=counts, prior_tail=tail,
            )
        )

    db.session.query(DutyAssignment).filter(
        DutyAssignment.date >= first,
        DutyAssignment.date <= last,
        DutyAssignment.is_manual.is_(False),
    ).delete()
    for (day, duty), person_id in picks.items():
        if person_id is None:
            continue  # blank day: no row — the page derives blanks (P4.5)
        db.session.add(
            DutyAssignment(
                date=day, duty=duty, person_id=person_id,
                is_manual=False, created_by_id=actor.id,
            )
        )
    db.session.commit()


class IneligibleAssignment(Exception):
    """Rule violation — a PC can never hold COS, and a weekend/holiday/blocked
    date carries no duty at all. Hard block, 4xx, never a warning."""


class NeedsAvailabilityConfirm(Exception):
    """Soft problems (decision d: the PS may assign over them with an explicit
    confirm). `reasons` is the user-facing list."""

    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class NotBlockable(Exception):
    """A date that cannot take a block (already a non-duty day, or already
    blocked); the message is user-facing."""


def _availability_reasons(person, day, duty):
    """Soft-warning reasons for putting `person` on (day, duty): covering
    absence or held duty, an excused platoon (decision (ee)), adjacency (incl.
    cross-month tail), spread breach.
    """
    month = day.strftime("%Y-%m")
    pools, availability, _manual = availability_for_month(month)
    reasons = []
    if not availability(person, day):
        reasons.append("covering absence or duty that day")
    if duty is Duty.COS:
        # Warn, never block (owner 2026-07-30): the excused platoon is the
        # unit's convention, and the PS may still key someone from it.
        category = platoon_service.cos_exclusions().get(person.platoon)
        if category is not None:
            reasons.append(
                f"Platoon {person.platoon} ({category.value}) is excluded from "
                "the COS pool"
            )
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
    """Assign/replace one (date, duty). The duty day and eligibility are LAW
    (hard block); availability/adjacency/spread are judgment (warn-then-confirm).
    Every manual assign marks the row `is_manual` — replacing the generator's
    pick is exactly how the PS resolves a clash, and regeneration must not undo
    it."""
    if day not in duty_days(day, day).active:
        raise IneligibleAssignment(
            f"{day.strftime('%d %b %Y')} is not a duty day — weekends, public "
            "holidays, and blocked days carry no COS or CDO/S."
        )
    rule = eligibility.eligible_cos if duty is Duty.COS else eligibility.eligible_cdos
    if not rule(person):
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
            is_manual=True, created_by_id=actor.id,
        )
        db.session.add(row)
    else:
        row.person_id = person.id
        row.is_manual = True
    db.session.commit()
    return row


def _holder_line(row):
    return f"{row.duty.label}: {row.person.rank.value} {row.person.display_name}"


def block_day(day, actor):
    """Mark `day` as needing no duty AND delete that date's assignments in ONE
    transaction — a block that left holders behind would show the grid one
    thing and the parade documents another. Returns the removed holders'
    descriptions so the caller can say who lost a duty.

    The duplicate-block guard is the UNIQUE date plus a caught IntegrityError,
    never a pre-check SELECT."""
    stamp = day.strftime("%d/%m")
    if day.weekday() >= 5:
        raise NotBlockable(f"{stamp} is a weekend — no duty is planned then anyway.")
    days = duty_days(day, day)
    if day in days.holidays:
        raise NotBlockable(
            f"{stamp} is a public holiday ({days.holidays[day]}) — no duty is "
            "planned then anyway."
        )
    # Read the holders BEFORE the pending insert exists: a later query would
    # autoflush it and raise the duplicate-block IntegrityError outside the
    # try below.
    holders = _assignments_between(day, day)
    removed = [_holder_line(row) for row in holders]
    db.session.add(DutyBlockedDay(date=day, created_by_id=actor.id))
    for row in holders:
        db.session.delete(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise NotBlockable(f"{stamp} is already blocked.")
    return removed


def unblock_day(day) -> bool:
    row = db.session.query(DutyBlockedDay).filter_by(date=day).first()
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def duties_on(day):
    """Assignments dated `day` — the consumers' notice helper (A7): when a
    night has no duty (rollout ramp, month boundary, blocked day), pages say so
    in chrome; the document text never changes."""
    return (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day)
        .order_by(DutyAssignment.duty)
        .all()
    )


def _holder(day, duty):
    row = (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day, DutyAssignment.duty == duty)
        .first()
    )
    return row.person if row is not None else None


def cos_of_day(day):
    """COS holder for `day`, or None (feeds the RO's COS line)."""
    return _holder(day, Duty.COS)


def cdos_of_day(day):
    """CDO/S holder for `day`, or None — P5's RO-rights input."""
    return _holder(day, Duty.CDOS)


def can_key_parade_today(person) -> bool:
    """The DB-aware wrapper every route and template calls: PS/S3/admin
    fallback OR COS for today or tomorrow (tomorrow's COS compiles day-D's
    message on the evening of D−1 — assumption 4 makes the two-day window the
    honest one). One duty query per page render — accepted at 40 users (A5); do
    not add caching. Rights are date-independent: the window decides WHO can
    key, not WHICH dates they may key."""
    today = today_sgt()
    is_cos = (
        db.session.query(DutyAssignment.id)
        .filter(
            DutyAssignment.person_id == person.id,
            DutyAssignment.duty == Duty.COS,
            DutyAssignment.date.in_((today, today + timedelta(days=1))),
        )
        .first()
        is not None
    )
    return policy.can_key_parade(person, is_cos_of_day=is_cos)


def _absent_assignment_ids(rows, first, last):
    """Assignment ids whose holder resolves ABSENT on the duty date, derived
    from the shared fetch (A8): an MC, a course, and approved leave all flag the
    same way, because the predicate IS presence, not a leave-table join.
    Never stored — recomputed at render."""
    if not rows:
        return frozenset()
    leaves, statuses, courses = presence_service.fetch_absence_rows(first, last)
    by_person = defaultdict(lambda: ([], [], []))
    for row in leaves:
        by_person[row.person_id][0].append(row)
    for row in statuses:
        by_person[row.person_id][1].append(row)
    for row in courses:
        by_person[row.person_id][2].append(row)
    flagged = set()
    for r in rows:
        p_leaves, p_statuses, p_courses = by_person.get(r.person_id, ((), (), ()))
        resolution = presence.resolve(
            r.person, r.date, leaves=p_leaves, statuses=p_statuses, courses=p_courses,
        )
        if resolution.state is presence.PresenceState.ABSENT:
            flagged.add(r.id)
    return frozenset(flagged)


DayRow = namedtuple("DayRow", "date holiday_name blocked")

MonthView = namedtuple(
    "MonthView",
    "first last days active rows by_slot pools assignable_pools violations absent_flags",
)


def month_view(month: str) -> MonthView:
    """Everything the roster page renders, assembled once. `days` is one row per
    WEEKDAY of the month, each tagged with its public-holiday name or its block;
    `active` is the subset that carries duties, and blanks/violations are
    derived over those alone. `violations` and `absent_flags` are re-derived
    from the CURRENT rows on every call (the pure module's contract: re-flag
    after manual edits, not only after generation). Blanks are slots with NO
    row — the DB never stores a None assignment.

    Two pool fields, deliberately: `pools` is the auto-pick pool the panel and
    the violations read; `assignable_pools` is the unfiltered eligibility pool
    the manual-assign dropdown reads, so a platoon excused the COS pool stays
    keyable-with-a-warning instead of vanishing from the page (decision (ee))."""
    first, last = month_bounds(month)
    dd = duty_days(first, last)
    rows = _assignments_between(first, last)
    by_slot = {(r.date, r.duty): r for r in rows}
    pools = _pools(event_service.active_roster())
    assignments = {
        (d, duty): (by_slot[(d, duty)].person_id if (d, duty) in by_slot else None)
        for d in dd.active
        for duty in Duty
    }
    _counts, prior_tail = _prior_month_inputs(first)
    return MonthView(
        first=first, last=last,
        days=[
            DayRow(date=d, holiday_name=dd.holidays.get(d), blocked=d in dd.blocked)
            for d in dd.weekdays
        ],
        active=dd.active,
        rows=rows, by_slot=by_slot,
        pools=pools.auto, assignable_pools=pools.assignable,
        violations=roster.violations(assignments, pools.auto, prior_tail=prior_tail),
        absent_flags=_absent_assignment_ids(rows, first, last),
    )
