"""Who is away / who is present — the single derivation that the away board,
month view, leave panel, and (from P3a.6) every parade document read.

There is exactly ONE fetch of the three presence sources (APPROVED leave +
regulars' direct absences + COS-keyed statuses). `absences_between` normalises
it to away-only `AbsenceRow`s (in-camp statuses dropped — in camp is not away);
`presence_inputs` resolves every active person through the pure precedence
engine (in-camp statuses kept, as annotations). Two views of one fetch, never
two fetches with different filters — a second derivation is exactly the drift
bug this app exists to kill. Semantics (precedence, day-part) live in
`app.domain.presence`; this module is the fetch/shape layer only.
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple

from app.domain import parade, presence
from app.domain.dates import iter_days
from app.domain.types import DayPart, RequestStatus
from app.extensions import db
from app.models import DirectAbsence, LeaveRequest, Person, StatusEntry


@dataclass(frozen=True)
class AbsenceRow:
    """One person's away-shaped row for a day, normalised across the three
    sources so the away surfaces read one type instead of three.

    `label` is the human tag (leave → LeaveType.value "OFF"; direct →
    DirectAbsenceType.label "Leave"; status → StatusType.label "MC"/"On
    course"). `in_camp` is False for leave/direct and the status row's own flag
    for statuses. `id` and `person_id` are convenience keys: the away surfaces
    dedupe on `person_id`, and `id` identifies the source row (the delegation
    check compares on it). `person` is the live Person model, so display fields
    ride along.
    """

    id: int
    person: object
    person_id: int
    label: str
    day_part: DayPart
    source: str  # "leave" | "direct" | "status"
    in_camp: bool
    remarks: object = None


def _fetch_rows(start_date, end_date):
    """The ONE query layer: APPROVED leave + direct absences + statuses that
    overlap [start_date, end_date] for ACTIVE people, each ordered platoon
    NULLS FIRST → display_name. Returns the ORIGINAL model rows as three lists.

    Extracting the leave/direct/status filter here (written once) is the whole
    point of the task: `absences_between` and `presence_inputs` are two views of
    THIS fetch, so they can never drift on which rows count.
    """

    def _overlapping(model, *extra):
        return (
            db.session.query(model)
            .join(Person, model.person_id == Person.id)
            .filter(
                model.start_date <= end_date,
                model.end_date >= start_date,
                Person.is_active.is_(True),
                *extra,
            )
            .order_by(Person.platoon.nulls_first(), Person.display_name)
            .all()
        )

    leaves = _overlapping(LeaveRequest, LeaveRequest.status == RequestStatus.APPROVED)
    directs = _overlapping(DirectAbsence)
    statuses = _overlapping(StatusEntry)
    return leaves, directs, statuses


def _absence_row(row, source):
    """Normalise one source model row to an AbsenceRow. `label` and `in_camp`
    are the only source-specific bits; the precedence rule is NOT re-implemented
    here (that lives in app.domain.presence)."""
    if source == "leave":
        label, in_camp = row.type.value, False
    elif source == "direct":
        label, in_camp = row.type.label, False
    else:  # status
        label, in_camp = row.type.label, row.in_camp
    return AbsenceRow(
        id=row.id,
        person=row.person,
        person_id=row.person_id,
        label=label,
        day_part=row.day_part,
        source=source,
        in_camp=in_camp,
        remarks=row.remarks,
    )


def absences_between(start_date, end_date):
    """Away rows (leave + direct absence + out-of-camp status) overlapping
    [start_date, end_date] for active people, bucketed per day.

    In-camp statuses are EXCLUDED — in camp is not away; they surface only in
    parade documents (via `presence_inputs`). All day-parts appear (the board
    shows a PM as a partial); the away-counting surfaces (month view, leave
    panel) dedupe on person_id and so now naturally include MC'd / direct-absent
    people.
    """
    leaves, directs, statuses = _fetch_rows(start_date, end_date)
    by_day = {d: [] for d in iter_days(start_date, end_date)}
    for source, rows in (("leave", leaves), ("direct", directs), ("status", statuses)):
        for row in rows:
            if source == "status" and row.in_camp:
                continue  # in camp ≠ away
            away = _absence_row(row, source)
            # Clip the row's range to the queried window before bucketing.
            first = max(row.start_date, start_date)
            last = min(row.end_date, end_date)
            for d in iter_days(first, last):
                by_day[d].append(away)
    # Re-order each day platoon NULLS FIRST → display_name across the three
    # merged sources (each was ordered alone). Stable sort, so a person's
    # overlapping rows keep fetch order (leave, then direct, then status).
    for rows in by_day.values():
        rows.sort(key=lambda a: (a.person.platoon or 0, a.person.display_name))
    return by_day


def absences_on(day):
    """Away rows covering `day` for active people — delegates to the range
    query so there is a single derivation."""
    return absences_between(day, day)[day]


def away_summary(day):
    """Board data: total strength, away rows grouped by platoon, and counts."""
    total = db.session.query(Person.id).filter_by(is_active=True).count()
    rows = absences_on(day)
    full_ids = {r.person_id for r in rows if r.day_part is DayPart.FULL}
    partial_ids = {r.person_id for r in rows if r.day_part is not DayPart.FULL} - full_ids
    groups: dict = {}
    for row in rows:
        key = f"Platoon {row.person.platoon}" if row.person.platoon else "HQ"
        groups.setdefault(key, []).append(row)
    return {
        "total": total,
        "away_full": len(full_ids),
        "away_partial": len(partial_ids),
        "groups": groups,
    }


def away_text(day, summary) -> str:
    """Plain-text rendition for pasting into WhatsApp."""
    lines = [
        f"AWAY — {day.strftime('%a %d %b %Y')}",
        f"Total strength: {summary['total']}",
        f"Away: {summary['away_full']} full-day, {summary['away_partial']} half-day",
    ]
    for group, rows in summary["groups"].items():
        lines.append("")
        lines.append(f"{group}:")
        for r in rows:
            part = "" if r.day_part is DayPart.FULL else f" ({r.day_part.value})"
            # Tag comes from the normalised label (MC/On course/Leave/OFF), so
            # every away surface shows the same word for the same row.
            lines.append(f"- {r.person.display_name} — {r.label}{part}")
    if not summary["groups"]:
        lines.append("")
        lines.append("Nobody away.")
    return "\n".join(lines)


class PersonPresence(NamedTuple):
    """One parade line's inputs: the person and their resolved presence.

    Paired here, NOT on the domain Resolution (its P3a.2 contract is fixed):
    a Resolution alone can't say whose it is, and parade documents must never
    zip resolutions back to people by list index.
    """

    person: object
    resolution: presence.Resolution


def presence_inputs(day):
    """Every ACTIVE person's resolved presence for `day` as parade-sorted
    `PersonPresence(person, resolution)` pairs — the one function every parade
    document reads (P3a.6+).

    Shares `_fetch_rows` with the away board (two views of one fetch); here ALL
    statuses are passed to the engine, so in-camp ones come back as annotations
    (`in_camp_rows`) rather than being dropped. The ORIGINAL model rows go to
    `resolve` — the engine returns the caller's own objects, and downstream
    rendering reads model fields (`.type`, `.remarks`, `.person`). Deactivated
    people are off the roster entirely, matching the away board.
    """
    leaves, directs, statuses = _fetch_rows(day, day)
    by_leave, by_direct, by_status = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in leaves:
        by_leave[row.person_id].append(row)
    for row in directs:
        by_direct[row.person_id].append(row)
    for row in statuses:
        by_status[row.person_id].append(row)

    people = db.session.query(Person).filter_by(is_active=True).all()
    people.sort(key=parade.parade_sort_key)  # parade display order (P3a.3)
    return [
        PersonPresence(
            person=person,
            resolution=presence.resolve(
                person,
                day,
                leaves=by_leave.get(person.id, ()),
                direct_absences=by_direct.get(person.id, ()),
                statuses=by_status.get(person.id, ()),
            ),
        )
        for person in people
    ]
