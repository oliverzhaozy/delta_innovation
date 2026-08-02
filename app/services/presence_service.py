"""Who is away / who is present — the single derivation that the month view,
leave panel, and (from P3a.6) every parade document read.

There is exactly ONE fetch of the presence sources (APPROVED leave + COS-keyed
statuses + TP-calendar course covers). `absences_between` normalises it to
away-only `AbsenceRow`s (in-camp statuses dropped — in camp is not away);
`presence_inputs` resolves every person through the pure precedence
engine (in-camp statuses kept, as annotations). Two views of one fetch, never
two fetches with different filters — a second derivation is exactly the drift
bug this app exists to kill. Semantics (precedence, day-part) live in
`app.domain.presence`; this module is the fetch/shape layer only.
"""
from collections import defaultdict, namedtuple
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import NamedTuple

from app.domain import parade, presence
from app.domain.dates import iter_days
from app.domain.events import event_days
from app.domain.types import (
    Calendar,
    CourseAbsenceType,
    DayPart,
    RequestStatus,
    Service,
    TpLabel,
)
from app.extensions import db
from app.models import DutyAssignment, Event, LeaveRequest, StatusEntry
from app.services import event_service


@dataclass(frozen=True)
class AbsenceRow:
    """One person's away-shaped row for a day, normalised across the sources so
    the away surfaces read one type instead of several.

    `label` is the human tag (leave → LeaveType.value "OFF"; status →
    StatusType.label "MC"). `in_camp` is False for leave and the status row's own
    flag for statuses. `id` and `person_id` are convenience keys: the away
    surfaces dedupe on `person_id`, and `id` identifies the source row (the
    delegation check compares on it). `person` is the live Person model, so
    display fields ride along.
    """

    id: int
    person: object
    person_id: int
    label: str
    day_part: DayPart
    source: str  # "leave" | "status" | "course"
    in_camp: bool
    remarks: object = None


# A course absence has no table: this adapter gives a TP course event × one of its
# participants the same duck-typed shape every other absence row has, so the pure
# engine and _absence_row need no course-specific branch beyond the kind marker.
# `id` is the source Event's id (identifies the row for the away surfaces),
# `day_part` is always FULL, and `remarks` carries the event title so the away
# panel reads "On course — Sig Course".
_CourseCover = namedtuple(
    "CourseCover", "id person person_id type start_date end_date day_part remarks"
)


def _course_covers(start_date, end_date):
    """One `_CourseCover` per (TP course event × resolved participant) overlapping
    [start_date, end_date], in parade order (appointment → rank) to match the
    fetches this sits beside.

    The date span of each event comes from `event_days` (the ONE owner of the
    times-ignored rule), never from `.date()` here. The SQL filter uses a
    datetime envelope over whole days so an event whose clock times fall outside
    the window but whose DATES overlap it is still a candidate.
    """
    envelope_start = datetime.combine(start_date, time.min)
    envelope_end = datetime.combine(end_date + timedelta(days=1), time.min)
    events = (
        db.session.query(Event)
        .filter(
            Event.calendar == Calendar.TP,
            Event.label == TpLabel.ON_COURSE.value,
            Event.start_dt < envelope_end,
            Event.end_dt > envelope_start,
        )
        .order_by(Event.start_dt, Event.id)
        .all()
    )
    covers = []
    for event in events:
        first, last = event_days(event.start_dt, event.end_dt)
        for person in event_service.resolve_participants(event):
            covers.append(
                _CourseCover(
                    id=event.id,
                    person=person,
                    person_id=person.id,
                    type=CourseAbsenceType.COURSE,
                    start_date=first,
                    end_date=last,
                    day_part=DayPart.FULL,
                    remarks=event.title,
                )
            )
    covers.sort(key=lambda c: (parade.parade_sort_key(c.person), c.id))
    return covers


def fetch_absence_rows(start_date, end_date):
    """The ONE query layer, now the shared public fetch that `absences_between`,
    `presence_inputs`, and duty availability (P4.4) all read: APPROVED leave +
    statuses + TP-calendar course covers that overlap [start_date, end_date],
    each in parade order (appointment → rank, then the row's own id). Returns
    the leave/status ORIGINAL model rows plus the synthesized course covers as
    three lists.

    Extracting the leave/status/course filter here (written once) is the whole
    point of the task: `absences_between` and `presence_inputs` are two views of
    THIS fetch, so they can never drift on which rows count.
    """

    def _overlapping(model, *extra):
        # The ORDER is parade order, which no column ORDER BY can express (enum
        # values sort by neither appointment nor seniority), so it happens in
        # Python over the rows.
        rows = (
            db.session.query(model)
            .filter(
                model.start_date <= end_date,
                model.end_date >= start_date,
                *extra,
            )
            .all()
        )
        rows.sort(key=lambda row: (parade.parade_sort_key(row.person), row.id))
        return rows

    leaves = _overlapping(LeaveRequest, LeaveRequest.status == RequestStatus.APPROVED)
    statuses = _overlapping(StatusEntry)
    courses = _course_covers(start_date, end_date)
    return leaves, statuses, courses


def _absence_row(row, source):
    """Normalise one source model row to an AbsenceRow. `label` and `in_camp`
    are the only source-specific bits; the precedence rule is NOT re-implemented
    here (that lives in app.domain.presence)."""
    if source == "leave":
        label, in_camp = row.type.value, False
    elif source == "course":
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
    """Away rows (leave + out-of-camp status + course) overlapping
    [start_date, end_date] for active people, bucketed per day.

    In-camp statuses are EXCLUDED — in camp is not away; they surface only in
    parade documents (via `presence_inputs`). All day-parts appear (the board
    shows a PM as a partial); the away-counting surfaces (the leave panel)
    dedupe on person_id and so naturally include MC'd and on-course people. The
    home month grid does NOT read this — it reads the leave-only
    `nsf_leave_between` layer, so MC/course never appear there.
    """
    leaves, statuses, courses = fetch_absence_rows(start_date, end_date)
    by_day = {d: [] for d in iter_days(start_date, end_date)}
    for source, rows in (("leave", leaves), ("status", statuses), ("course", courses)):
        for row in rows:
            if source == "status" and row.in_camp:
                continue  # in camp ≠ away
            away = _absence_row(row, source)
            # Clip the row's range to the queried window before bucketing.
            first = max(row.start_date, start_date)
            last = min(row.end_date, end_date)
            for d in iter_days(first, last):
                by_day[d].append(away)
    # Re-order each day into parade order across the merged sources (each was
    # ordered alone). Stable sort, so a person's overlapping rows keep fetch
    # order (leave, then status, then course).
    for rows in by_day.values():
        rows.sort(key=lambda a: parade.parade_sort_key(a.person))
    return by_day


def nsf_leave_between(start_date, end_date):
    """The DELTA NSF OFF/LEAVE calendar layer: per-day buckets of NSF personnel
    on APPROVED leave (OFF/OIL/LL/OL) over [start_date, end_date].

    A filtered VIEW of `absences_between`, never a second query — same single
    derivation. Keeps only leave-sourced rows (source == "leave" is exactly the
    APPROVED LeaveRequest rows; MC/other statuses and course covers are other
    layers) whose person is NSF. Each day's list stays in the parent's parade
    order.
    """
    return {
        day: [r for r in rows if r.source == "leave" and r.person.service is Service.NSF]
        for day, rows in absences_between(start_date, end_date).items()
    }


def absences_on(day):
    """Away rows covering `day` for active people — delegates to the range
    query so there is a single derivation."""
    return absences_between(day, day)[day]


class PersonPresence(NamedTuple):
    """One parade line's inputs: the person and their resolved presence.

    Paired here, NOT on the domain Resolution (its P3a.2 contract is fixed):
    a Resolution alone can't say whose it is, and parade documents must never
    zip resolutions back to people by list index.
    """

    person: object
    resolution: presence.Resolution


_DutyCover = namedtuple("DutyCover", "start_date end_date")


def presence_inputs(day, *, duty_day=None):
    """Every person's resolved presence for `day` as parade-sorted
    `PersonPresence(person, resolution)` pairs — the one function every parade
    document reads (P3a.6+).

    Shares `fetch_absence_rows` with the away board (two views of one fetch); here ALL
    statuses are passed to the engine, so in-camp ones come back as annotations
    (`in_camp_rows`) rather than being dropped. The ORIGINAL model rows go to
    `resolve` — the engine returns the caller's own objects, and downstream
    rendering reads model fields (`.type`, `.remarks`, `.person`).

    `duty_day` (keyword-only): which date's duty_assignment rows feed
    the DUTY state — the fetch key ONLY. The adapter row handed to the engine
    covers start=end=`day` (the resolution day), because `covers()` compares
    against the day being resolved (A3): roll call labeled D covers the night
    D−1→D, so its build passes duty_day=D−1 but the duty must count ON day D.
    The COS message for D covers that same night, so it passes D−1 too (owner
    2026-08-02). Default None means the duty of `day` itself (morning parade).
    """
    leaves, statuses, courses = fetch_absence_rows(day, day)
    duty_rows = (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == (duty_day if duty_day is not None else day))
        .all()
    )
    by_duty = defaultdict(list)
    for row in duty_rows:
        by_duty[row.person_id].append(_DutyCover(start_date=day, end_date=day))
    by_leave, by_status, by_course = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in leaves:
        by_leave[row.person_id].append(row)
    for row in statuses:
        by_status[row.person_id].append(row)
    for row in courses:
        by_course[row.person_id].append(row)

    # THE roster order (P3a.3), read from its one owner rather than re-sorted here.
    people = event_service.active_roster()
    return [
        PersonPresence(
            person=person,
            resolution=presence.resolve(
                person,
                day,
                leaves=by_leave.get(person.id, ()),
                statuses=by_status.get(person.id, ()),
                courses=by_course.get(person.id, ()),
                duties=by_duty.get(person.id, ()),
            ),
        )
        for person in people
    ]
