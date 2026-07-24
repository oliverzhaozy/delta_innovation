"""Greedy monthly duty generator (P4.3). Pure: stdlib + sibling app.domain.

Hard constraints are structural: eligibility arrives as pre-filtered `pools`,
availability as a predicate — an unfillable (day, duty) is left None and
flagged, never rule-broken (decision d: auto-pick skips anyone with any
off/leave; the PS's manual-assign-with-warning is the only path over that
line). Soft constraints — per-duty spread max-min <= 1 within the month, no
adjacent duty days including Fri -> following Mon (assumption 11) — steer the
pick key and are REPORTED by violations(), never solved and never refused:
at 36 people an unfair Tuesday is a conversation, not an optimization problem.
No solver, no randomness — identical inputs generate identical rosters.

`violations()` is deliberately standalone: the roster page re-flags on every
render, after manual edits, not only after generation.

`prior_tail` = (day, duty, person_id) rows from the LAST 3 CALENDAR DAYS of
the previous month (Fri -> Mon adjacency can reach 3 days back); `prior_counts`
= previous month's per-person totals, consulted as a tie-breaker ONLY. Both
empty on the first-ever month: an empty tail means no adjacency constraint
from the past — defined, not crashed.
"""
from collections import defaultdict, namedtuple
from datetime import date

_FRIDAY, _MONDAY = 4, 0

Violations = namedtuple("Violations", "blanks adjacency spread")


def adjacent_duty_days(d1: date, d2: date) -> bool:
    """Calendar-adjacent OR the (Friday, following Monday) pair. Symmetric;
    the same day is not adjacent to itself."""
    if d1 == d2:
        return False
    a, b = (d1, d2) if d1 < d2 else (d2, d1)
    if (b - a).days == 1:
        return True
    return a.weekday() == _FRIDAY and b.weekday() == _MONDAY and (b - a).days == 3


def generate(days, pools, availability, prior_counts=None, prior_tail=()):
    """{(day, duty): person_id | None} for the ordered `days`.

    `pools` = {Duty: [person, ...]} pre-filtered (eligible AND active), stable
    order. `availability(person, day) -> bool` is the hard gate. Pick key per
    (day, duty), smallest wins: (creates_adjacency, this_month_count_for_duty,
    carry_over_count, pool_position) — adjacency avoidance beats evenness,
    evenness beats history, position pins determinism.
    """
    prior_counts = prior_counts or {}
    duty_dates = defaultdict(set)  # person_id -> every duty date held (any duty)
    for day, _duty, person_id in prior_tail:
        if person_id is not None:
            duty_dates[person_id].add(day)
    month_counts = {duty: defaultdict(int) for duty in pools}
    assignments = {}

    for day in days:
        for duty, members in pools.items():
            candidates = [p for p in members if availability(p, day)]
            if not candidates:
                assignments[(day, duty)] = None
                continue

            def pick_key(indexed):
                position, p = indexed
                creates_adjacency = any(
                    adjacent_duty_days(day, held) for held in duty_dates[p.id]
                )
                return (
                    creates_adjacency,
                    month_counts[duty][p.id],
                    prior_counts.get(duty, {}).get(p.id, 0),
                    position,
                )

            _, pick = min(enumerate(candidates), key=pick_key)
            assignments[(day, duty)] = pick.id
            month_counts[duty][pick.id] += 1
            duty_dates[pick.id].add(day)

    return assignments


def violations(assignments, pools, prior_tail=()):
    """Re-derive every soft breach and blank from ANY assignment map (fresh
    generation or manual edits — the function does not care which).

    Returns Violations(blanks=[(day, duty)...], adjacency=[(person_id, d1, d2)
    with d1 < d2 ...], spread={duty: (min, max)} for breached duties only).
    Spread counts every POOL member, including those at zero — a man the
    generator never picked is exactly what the spread rule exists to surface.
    """
    blanks = sorted((day, duty) for (day, duty), pid in assignments.items() if pid is None)

    dates_by_person = defaultdict(set)
    for (day, _duty), pid in assignments.items():
        if pid is not None:
            dates_by_person[pid].add(day)
    for day, _duty, pid in prior_tail:
        if pid is not None:
            dates_by_person[pid].add(day)
    adjacency = sorted(
        (pid, a, b)
        for pid, held in dates_by_person.items()
        for a in held
        for b in held
        if a < b and adjacent_duty_days(a, b)
    )

    spread = {}
    for duty, members in pools.items():
        if not members:
            continue
        counts = {p.id: 0 for p in members}
        for (_day, d), pid in assignments.items():
            if d is duty and pid in counts:
                counts[pid] += 1
        lo, hi = min(counts.values()), max(counts.values())
        if hi - lo > 1:
            spread[duty] = (lo, hi)

    return Violations(blanks=blanks, adjacency=adjacency, spread=spread)
