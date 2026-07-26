"""Pure presence precedence engine (Phase 3): resolve one person's state for
one day from pre-filtered, duck-typed rows. Every parade document and the away
board read presence through this module, so the precedence rule and the
day-part semantics are the semantic core of the phase.

The caller pre-filters and passes rows for a SINGLE person: `leaves` are
APPROVED leave rows only (this module never sees a status field — the approval
decision is upstream in the leave flow), `statuses` are COS-keyed exceptions
(MC/other), `courses` are covers derived from TP calendar course events, and
`duties` are CONFIRMED duty covers. Rows are duck-typed: every row exposes
`.start_date`, `.end_date`, `.day_part`; status rows additionally expose
`.in_camp`. The engine never copies a row — it returns the caller's own objects
so downstream rendering keeps every field.

Regulars are NOT tracked here (owner directive 2026-07-26): their off/leave
lives in the external ARCTIC FOE system, so a regular appears in current
strength unless a keyed status or a course says otherwise.

Precedence (highest wins), matching TECH_PLAN's parade precedence rule:

    deactivated
      > approved leave
      > out-of-camp status                (MC / other…)
      > course                            (derived from the TP calendar)
      > duty
      > stay-out                          (stay_out flag OR REGULAR service)
      > present

A keyed status outranks a derived course: the COS keyed the MC deliberately, the
course cover is inferred. The loser still lands in `conflicts`.

Only FULL and AM absences take the person off the parade for the day
(`absent_for_day`, decision (i)); a PM absence leaves them PRESENT but is
surfaced in `partial_rows` so callers can tag "(PM)". In-camp statuses are
NEVER absences: they are annotations returned in `in_camp_rows` regardless of
which state wins — a stay-out regular on an in-camp OTHER (e.g. a briefing) is
STAY_OUT for the night documents, with the annotation feeding OTHERS IN CAMP on
the morning one.
Every covering absent-making row that does not win is returned in `conflicts`
(e.g. an MC keyed while the person is already on approved leave), so the keyer
sees it; nothing a covering row says is ever silently dropped.
"""
import enum
from dataclasses import dataclass

from app.domain.types import DayPart, Service


class PresenceState(str, enum.Enum):
    # Presence vocabulary lives in this module, not types.py: it has a single
    # consumer family (the parade engine + its documents), not general domain
    # vocabulary shared across blueprints.
    DEACTIVATED = "DEACTIVATED"
    ABSENT = "ABSENT"
    DUTY = "DUTY"
    STAY_OUT = "STAY_OUT"
    PRESENT = "PRESENT"


@dataclass(frozen=True)
class Resolution:
    """One person's resolved presence for one day.

    `row` is the single winning absence-making row (set only when `state` is
    ABSENT). `partial_rows` are covering rows that are away for only part of the
    day (PM) — present for parade, tagged "(PM)". `in_camp_rows` are covering
    in-camp statuses (annotations → OTHERS IN CAMP). `conflicts` are covering
    absent-making rows that lost to the winner — or all of them when deactivated,
    since there is no winner then — surfaced to the keyer, never dropped.
    """

    state: PresenceState
    row: object = None
    partial_rows: tuple = ()
    in_camp_rows: tuple = ()
    conflicts: tuple = ()


def covers(row, day) -> bool:
    """True if `day` falls within the row's inclusive [start_date, end_date]."""
    return row.start_date <= day <= row.end_date


def absent_for_day(day_part) -> bool:
    """Whether a `day_part` absence takes the person off the parade for the day.

    THE single place this rule lives (decision (i)): FULL and AM count as absent
    for both roll call and morning parade; PM does not (expected back at night —
    decision (c)). A future flip of the AM policy is this one line.
    """
    return day_part in (DayPart.FULL, DayPart.AM)


def resolve(person, day, *, leaves=(), statuses=(), courses=(), duties=()) -> Resolution:
    """Resolve `person`'s presence for `day` from the pre-filtered rows.

    See the module docstring for the input contract and the precedence rule.
    """
    # Absent-making rows in precedence order — leave, then out-of-camp status,
    # then course — so the first is the winner and the rest are conflicts.
    absent_making = []
    partial_rows = []
    in_camp_rows = []

    # Leaves are always out of camp (they carry no in_camp field): FULL/AM make
    # absent, PM is a partial (present, tagged "(PM)").
    for row in leaves:
        if not covers(row, day):
            continue
        if absent_for_day(row.day_part):
            absent_making.append(row)
        else:
            partial_rows.append(row)

    # Statuses split on in_camp: in-camp ones are annotations only (never an
    # absence, whatever their day_part); out-of-camp ones make absent under the
    # same FULL/AM rule and rank below leave.
    out_of_camp_absent = []
    for row in statuses:
        if not covers(row, day):
            continue
        if row.in_camp:
            in_camp_rows.append(row)
        elif absent_for_day(row.day_part):
            out_of_camp_absent.append(row)
        else:
            partial_rows.append(row)
    absent_making.extend(out_of_camp_absent)

    # Course covers are always out of camp for the whole day (owner decision 3),
    # so no day_part branch: covering at all means absent-making. They rank last
    # among the absent-makers — a keyed status is a deliberate act, a course cover
    # is derived — and a loser still surfaces in `conflicts`.
    for row in courses:
        if covers(row, day):
            absent_making.append(row)

    covering_duty = any(covers(row, day) for row in duties)

    if not person.is_active:
        # Deactivated wins outright, but every covering row is still classified
        # so nothing a row says vanishes: with no winner, all absent-makers are
        # conflicts (partials/in-camp are already collected above).
        state = PresenceState.DEACTIVATED
        winner = None
        conflicts = tuple(absent_making)
    elif absent_making:
        state = PresenceState.ABSENT
        winner = absent_making[0]
        conflicts = tuple(absent_making[1:])
    elif covering_duty:
        state = PresenceState.DUTY
        winner = None
        conflicts = ()
    elif person.stay_out or person.service is Service.REGULAR:
        # Regulars default to stay-out unless an absence/status/duty overrode.
        state = PresenceState.STAY_OUT
        winner = None
        conflicts = ()
    else:
        state = PresenceState.PRESENT
        winner = None
        conflicts = ()

    return Resolution(
        state=state,
        row=winner,
        partial_rows=tuple(partial_rows),
        in_camp_rows=tuple(in_camp_rows),
        conflicts=conflicts,
    )
