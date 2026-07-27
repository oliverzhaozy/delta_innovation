"""Builds the month-grid context shared by the calendar month view and the
home page ("/"). Extracted so both endpoints render ONE overlay (TP + ARCTIC
events + the derived NSF OFF/LEAVE layer) from one code path — no drift, and
no logic duplicated between the two routes.

The grid is a stack of WEEK rows, not 42 independent day cells: an event or a
contiguous OFF/LEAVE run becomes one spanning bar per week (UI-23), so nothing
is duplicated across the days it covers. `app.domain.monthgrid` owns the
geometry; this module only decides which rows exist and which band they sit in.
Grid rows within a week: row 1 is the day-number head, the lanes follow from
row 2 (events band on top, OFF/LEAVE band under it), then a filler row.
"""
import calendar as stdlib_calendar
from datetime import date, datetime, time

from app.domain import monthgrid, policy
from app.domain.dates import today_sgt
from app.domain.types import Calendar
from app.extensions import db
from app.models import Event
from app.services import presence_service

# How many lanes of OFF/LEAVE bars a week shows before collapsing the rest into
# per-day "+N more" chips — the phone-width cap that keeps the grid readable.
OFF_LEAVE_CHIP_LIMIT = 3

# Row 1 of a week grid is the day-number head, so the first lane is row 2.
FIRST_LANE_ROW = 2


def _month_bounds(year, month):
    start = date(year, month, 1)
    end_exclusive = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end_exclusive


def _dedupe_by_person(rows):
    seen = set()
    out = []
    for row in rows:
        if row.person_id in seen:
            continue
        seen.add(row.person_id)
        out.append(row)
    return out


def _adjacent_ym(year, month, delta):
    # delta is +-1 month; only ever called with |delta| == 1 so no general
    # modular-arithmetic case is needed.
    if delta == 1:
        return (year + 1, 1) if month == 12 else (year, month + 1)
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _bar(*, kind, obj, segment, row):
    return {
        "kind": kind,
        "obj": obj,
        "col": segment.col,
        "span": segment.span,
        "row": row,
        "clip_left": segment.clip_left,
        "clip_right": segment.clip_right,
    }


def _place(intervals, week_days):
    """(source, Segment) for every (source, first, last) interval touching this
    week row; intervals that miss its in-month days drop out."""
    placed = []
    for source, first, last in intervals:
        segment = monthgrid.week_segment(start=first, end=last, week_days=week_days)
        if segment is not None:
            placed.append((source, segment))
    return placed


def _week_context(*, event_spans, off_runs, week_days):
    """One week row: its 7 cells, plus every bar already placed on a grid row.

    The two bands keep the day cell's old top-to-bottom order — events above
    OFF/LEAVE. The events band is uncapped; the OFF/LEAVE band shows at most
    `OFF_LEAVE_CHIP_LIMIT` lanes and folds whatever is pushed past them into one
    row of per-day "+N more" chips.
    """
    event_placed = _place(event_spans, week_days)
    event_lanes = monthgrid.pack_lanes([segment.col_span for _, segment in event_placed])
    event_lane_count = max(event_lanes) + 1 if event_lanes else 0

    off_placed = _place(off_runs, week_days)
    off_placements = [segment.col_span for _, segment in off_placed]
    off_lanes = monthgrid.pack_lanes(off_placements)
    overflow = monthgrid.overflow_by_column(
        off_placements, off_lanes, lane_limit=OFF_LEAVE_CHIP_LIMIT
    )
    shown_off_lanes = [lane for lane in off_lanes if lane < OFF_LEAVE_CHIP_LIMIT]
    off_lane_count = max(shown_off_lanes) + 1 if shown_off_lanes else 0

    bars = []
    for (event, segment), lane in zip(event_placed, event_lanes):
        bars.append(_bar(kind="event", obj=event, segment=segment, row=FIRST_LANE_ROW + lane))
    for (row, segment), lane in zip(off_placed, off_lanes):
        if lane >= OFF_LEAVE_CHIP_LIMIT:
            continue
        bars.append(
            _bar(
                kind="off",
                obj=row,
                segment=segment,
                row=FIRST_LANE_ROW + event_lane_count + lane,
            )
        )
    more_row = FIRST_LANE_ROW + event_lane_count + off_lane_count
    for column in sorted(overflow):
        bars.append(
            {
                "kind": "more",
                "count": overflow[column],
                "col": column,
                "span": 1,
                "row": more_row,
                "clip_left": False,
                "clip_right": False,
            }
        )

    lanes = event_lane_count + off_lane_count + (1 if overflow else 0)
    return {
        "cells": [{"date": day, "in_month": in_month} for day, in_month in week_days],
        "segments": bars,
        # The CSS repeat(var(--lanes), ...) needs a track even on an empty week.
        "lane_count": max(lanes, 1),
    }


def build_month_context(user, ym_raw):
    """Return the template context for `calendar/month.html` for `user`.

    `ym_raw` is the raw `?ym=YYYY-MM` string ("" for the current month); a bad
    value falls back to today, mirroring the parade morning page's bad-?date=
    convention (fall back, never 404).
    """
    today = today_sgt()
    year, month_num = today.year, today.month
    if ym_raw:
        try:
            year_str, month_str = ym_raw.split("-")
            year, month_num = int(year_str), int(month_str)
            month_start, month_end_exclusive = _month_bounds(year, month_num)
        except ValueError:
            year, month_num = today.year, today.month
            month_start, month_end_exclusive = _month_bounds(year, month_num)
    else:
        month_start, month_end_exclusive = _month_bounds(year, month_num)
    month_end_inclusive = date.fromordinal(month_end_exclusive.toordinal() - 1)

    show_arctic = policy.can_view_arctic(user)
    events = (
        db.session.query(Event)
        .filter(
            Event.start_dt < datetime.combine(month_end_exclusive, time.min),
            Event.end_dt > datetime.combine(month_start, time.min),
        )
        .order_by(Event.start_dt)
        .all()
    )
    event_spans = []
    for event in events:
        # ARCTIC filtered server-side, same rule as the list/detail routes —
        # never trust the template to hide rows it shouldn't have.
        if event.calendar is Calendar.ARCTIC and not show_arctic:
            continue
        # .date() on both ends, inclusive: an event ending at 00:00 still
        # occupies that calendar day. Acceptable simplification for a bar
        # display — not the precise clash-check semantics of a later task.
        # Clipped to the month: the neighbouring month draws its own bar.
        first = max(event.start_dt.date(), month_start)
        last = min(event.end_dt.date(), month_end_inclusive)
        event_spans.append((event, first, last))

    # The derived NSF OFF/LEAVE layer — a filtered view of the one absence
    # derivation, so it can never drift from the away board. One run per PERSON:
    # a person may hold overlapping approved requests, but the grid shows people
    # (like the away board), not rows. Order is preserved (already platoon → name).
    off_leave_by_day = presence_service.nsf_leave_between(month_start, month_end_inclusive)
    off_runs = [
        (run.row, run.start, run.end)
        for run in monthgrid.merge_off_runs(
            {day: _dedupe_by_person(rows) for day, rows in off_leave_by_day.items()}
        )
    ]

    weeks = []
    for week in stdlib_calendar.Calendar(firstweekday=0).monthdatescalendar(year, month_num):
        # Adjacent-month padding cells carry no bars at all (TECH_PLAN cut).
        week_days = [(d, d.month == month_num and d.year == year) for d in week]
        weeks.append(_week_context(event_spans=event_spans, off_runs=off_runs, week_days=week_days))

    return {
        "month_start": month_start,
        "weekday_labels": list(stdlib_calendar.day_abbr),
        "weeks": weeks,
        "prev_ym": "%04d-%02d" % _adjacent_ym(year, month_num, -1),
        "next_ym": "%04d-%02d" % _adjacent_ym(year, month_num, 1),
        "today_ym": "%04d-%02d" % (today.year, today.month),
        "show_arctic": show_arctic,
    }
