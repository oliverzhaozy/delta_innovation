"""Builds the month-grid context for the calendar month view — the ONE overlay
(TP + ARCTIC events + the derived NSF OFF/LEAVE layer) the grid renders from.
Kept a module of its own now that `calendar.month` is the single caller,
because the geometry below is the whole of the page and none of the route.

The grid is a stack of WEEK rows, not 42 independent day cells: an event or a
contiguous OFF/LEAVE run becomes one spanning bar per week (UI-23), so nothing
is duplicated across the days it covers. `app.domain.monthgrid` owns the
geometry; this module only decides which rows exist and which band they sit in.
Grid rows within a week: row 1 is the day-number head, the lanes follow from
row 2 (events band on top, OFF/LEAVE band under it), then a filler row. The
OFF/LEAVE band floors PER COLUMN — a chip packs flush under the events of the
days it covers, not under the week's tallest event stack.

ONE cap (UI-24) then applies to the whole stack rather than to either band: the
bars past it are dropped and folded into per-day "+N" badges, so a busy week
stays phone-height whichever layer filled it. The same context also carries
`day_entries` — the full, uncapped per-day list the day-detail panel opens —
built from the SAME clipped event spans the bars come from, so nothing the grid
hides can go missing from the panel.
"""
import calendar as stdlib_calendar
from datetime import date, datetime, time

from app.domain import monthgrid, policy
from app.domain.dates import adjacent_ym, iter_days, parse_ym, today_sgt
from app.domain.events import ALL_DAY_DISPLAY, day_time_display, event_days, is_all_day
from app.domain.types import Calendar
from app.extensions import db
from app.models import Event
from app.services import presence_service

# How many lanes of bars a week shows before the rest collapse into per-day "+N"
# badges — the phone-width cap that keeps the grid readable. ONE cap over the
# whole stack (events + OFF/LEAVE), not one per band. An overflowing column puts
# its badge flush under its last shown bar, so a week is at most
# TOTAL_LANE_LIMIT + 1 rows of bars tall.
TOTAL_LANE_LIMIT = 5

# Row 1 of a week grid is the day-number head, so the first lane is row 2.
FIRST_LANE_ROW = 2

# The client-side layer-toggle key the OFF/LEAVE layer's chips and panel entries
# share; events get theirs from `_cal_key`.
OFF_CAL_KEY = "off"


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


def _cal_key(event):
    """The client-side layer-toggle key an event's chip, its "+N" contribution
    and its panel entry all share — one owner, so a badge count can never
    disagree with the chips the same toggle hides."""
    return "arctic" if event.calendar is Calendar.ARCTIC else "tp"


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


def _week_context(*, event_spans, off_runs, week_days, today):
    """One week row: its 7 cells, plus every bar already placed on a grid row.

    The two bands keep the day cell's old top-to-bottom order — events above
    OFF/LEAVE — but per column, not per week: an OFF/LEAVE chip floors under
    the events of the days IT covers, so a quiet day's chips hug that day's
    last event instead of reserving rows for the week's tallest stack.

    Then ONE cap applies to the packed stack, band-blind (UI-24): a bar landing
    on lane `TOTAL_LANE_LIMIT` or past it is dropped, whichever band it came
    from, and every DAY it covered counts it into that day's "+N" badge. The
    badge sits flush under its column's last SHOWN bar and carries both the
    total and a per-toggle-key breakdown, so hiding a layer client-side can
    re-count it without another request.
    """
    event_placed = _place(event_spans, week_days)
    event_placements = [segment.col_span for _, segment in event_placed]
    event_lanes = monthgrid.pack_lanes(event_placements)

    off_placed = _place(off_runs, week_days)
    off_placements = [segment.col_span for _, segment in off_placed]
    off_lanes = monthgrid.pack_lanes(
        off_placements,
        floors=monthgrid.floors_under(
            off_placements, tops=monthgrid.lane_tops(event_placements, event_lanes)
        ),
    )

    placed = [
        ("event", event, segment, lane, _cal_key(event))
        for (event, segment), lane in zip(event_placed, event_lanes)
    ] + [
        ("off", row, segment, lane, OFF_CAL_KEY)
        for (row, segment), lane in zip(off_placed, off_lanes)
    ]

    bars = []
    shown_placements = []
    shown_lanes = []
    by_key = {}
    for kind, obj, segment, lane, cal_key in placed:
        key_placements, key_lanes = by_key.setdefault(cal_key, ([], []))
        key_placements.append(segment.col_span)
        key_lanes.append(lane)
        if lane >= TOTAL_LANE_LIMIT:
            continue
        bars.append(_bar(kind=kind, obj=obj, segment=segment, row=FIRST_LANE_ROW + lane))
        shown_placements.append(segment.col_span)
        shown_lanes.append(lane)

    # `overflow_by_column` stays the one owner of "which days a dropped bar is
    # counted into"; the split is just calling it once per toggle key, so the
    # breakdown and the total can't be derived two different ways.
    counts_by_column = {}
    for cal_key, (key_placements, key_lanes) in by_key.items():
        dropped = monthgrid.overflow_by_column(
            key_placements, key_lanes, lane_limit=TOTAL_LANE_LIMIT
        )
        for column, count in dropped.items():
            counts_by_column.setdefault(column, {})[cal_key] = count

    shown_tops = monthgrid.lane_tops(shown_placements, shown_lanes)
    for column in sorted(counts_by_column):
        counts = counts_by_column[column]
        bars.append(
            {
                "kind": "more",
                "count": sum(counts.values()),
                "counts": counts,
                "col": column,
                "span": 1,
                "row": FIRST_LANE_ROW + shown_tops.get(column, -1) + 1,
                "clip_left": False,
                "clip_right": False,
            }
        )

    lanes = max((bar["row"] - FIRST_LANE_ROW + 1 for bar in bars), default=0)
    return {
        # `is_today` is in-month only: a padding cell is the NEIGHBOURING month's
        # day, already muted, and ringing it would claim this month contains it.
        "cells": [
            {"date": day, "in_month": in_month, "is_today": in_month and day == today}
            for day, in_month in week_days
        ],
        "segments": bars,
        # The CSS repeat(var(--lanes), ...) needs a track even on an empty week.
        # A badge can only ever sit one lane below the cap, so this stays <= 6.
        "lane_count": max(lanes, 1),
    }


def _entry(*, kind, cal_key, obj, time_display):
    """One day-detail panel line. `obj` is the live Event / AbsenceRow so the
    template reuses the display expressions the chips already use."""
    return {"kind": kind, "cal_key": cal_key, "obj": obj, "time_display": time_display}


def _day_entries(*, event_spans, off_by_day, month_start, month_end_inclusive):
    """Ordered panel entries for EVERY day of the month, keyed by date.

    Every day gets a key, quiet ones included — clicking any cell opens the
    panel, and an empty list is what "nothing on" looks like. Events walk the
    same month-clipped spans the BARS are drawn from, so the panel and the grid
    can never disagree about which days an event covers.

    Order within a day follows the grid's bands and TimeTree's panel: entries
    that own the whole day first — all-day and multi-day events, then the
    OFF/LEAVE people — and the day's timed events after them, by start time.
    """
    days = list(iter_days(month_start, month_end_inclusive))
    all_day = {day: [] for day in days}
    off = {day: [] for day in days}
    timed = {day: [] for day in days}

    for event, first, last in event_spans:
        event_first, event_last = event_days(event.start_dt, event.end_dt)
        whole_day = event_first != event_last or is_all_day(event.start_dt, event.end_dt)
        for day in iter_days(first, last):
            entry = _entry(
                kind="event",
                cal_key=_cal_key(event),
                obj=event,
                time_display=day_time_display(event.start_dt, event.end_dt, day),
            )
            (all_day if whole_day else timed)[day].append(entry)

    for day, rows in off_by_day.items():
        off[day] = [
            _entry(kind="off", cal_key=OFF_CAL_KEY, obj=row, time_display=ALL_DAY_DISPLAY)
            for row in rows
        ]

    for entries in timed.values():
        entries.sort(key=lambda entry: entry["obj"].start_dt)
    return {day: all_day[day] + off[day] + timed[day] for day in days}


def build_month_context(user, ym_raw):
    """Return the template context for `calendar/month.html` for `user`.

    `ym_raw` is the raw `?ym=YYYY-MM` string ("" for the current month); a bad
    value falls back to today via the shared `parse_ym`, mirroring the parade
    morning page's bad-?date= convention (fall back, never 404).
    """
    today = today_sgt()
    year, month_num = parse_ym(ym_raw)
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
    # Deduped ONCE: the bars' runs and the panel's lines are the same people in
    # the same order, so neither can show a person the other drops.
    off_by_day = {day: _dedupe_by_person(rows) for day, rows in off_leave_by_day.items()}
    off_runs = [
        (run.row, run.start, run.end) for run in monthgrid.merge_off_runs(off_by_day)
    ]

    weeks = []
    for week in stdlib_calendar.Calendar(firstweekday=0).monthdatescalendar(year, month_num):
        # Adjacent-month padding cells carry no bars at all (TECH_PLAN cut).
        week_days = [(d, d.month == month_num and d.year == year) for d in week]
        weeks.append(
            _week_context(
                event_spans=event_spans,
                off_runs=off_runs,
                week_days=week_days,
                today=today,
            )
        )

    return {
        "month_start": month_start,
        "weekday_labels": list(stdlib_calendar.day_abbr),
        "weeks": weeks,
        "prev_ym": "%04d-%02d" % adjacent_ym(year, month_num, -1),
        "next_ym": "%04d-%02d" % adjacent_ym(year, month_num, 1),
        "today_ym": "%04d-%02d" % (today.year, today.month),
        "show_arctic": show_arctic,
        # Uncapped: the badges hide bars from the GRID, never from the panel.
        "day_entries": _day_entries(
            event_spans=event_spans,
            off_by_day=off_by_day,
            month_start=month_start,
            month_end_inclusive=month_end_inclusive,
        ),
    }
