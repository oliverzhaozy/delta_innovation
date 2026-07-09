"""Builds the month-grid context shared by the calendar month view and the
home page ("/"). Extracted so both endpoints render ONE overlay (TP + ARCTIC
events + the derived NSF OFF/LEAVE layer) from one code path — no drift, and
no logic duplicated between the two routes.
"""
import calendar as stdlib_calendar
from datetime import date, datetime, time

from app.domain import policy
from app.domain.dates import iter_days, today_sgt
from app.domain.types import Calendar
from app.extensions import db
from app.models import Event
from app.services import presence_service

# How many OFF/LEAVE name chips a day cell shows before collapsing the rest
# into a "+N more" link — the phone-width cap that keeps the grid readable.
OFF_LEAVE_CHIP_LIMIT = 3


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


def build_month_context(user, ym_raw):
    """Return the template context for `calendar/month.html` for `user`.

    `ym_raw` is the raw `?ym=YYYY-MM` string ("" for the current month); a bad
    value falls back to today, mirroring parade.away's bad-?date= convention
    (fall back, never 404).
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
    events_by_day = {d: [] for d in iter_days(month_start, month_end_inclusive)}
    for event in events:
        # ARCTIC filtered server-side, same rule as the list/detail routes —
        # never trust the template to hide rows it shouldn't have.
        if event.calendar is Calendar.ARCTIC and not show_arctic:
            continue
        # .date() on both ends, inclusive: an event ending at 00:00 still
        # occupies that calendar day. Acceptable simplification for a chip
        # display — not the precise clash-check semantics of a later task.
        first = max(event.start_dt.date(), month_start)
        last = min(event.end_dt.date(), month_end_inclusive)
        for d in iter_days(first, last):
            events_by_day[d].append(event)

    # The derived NSF OFF/LEAVE layer — a filtered view of the one absence
    # derivation, so it can never drift from the away board.
    off_leave_by_day = presence_service.nsf_leave_between(month_start, month_end_inclusive)

    weeks = []
    for week in stdlib_calendar.Calendar(firstweekday=0).monthdatescalendar(year, month_num):
        cells = []
        for d in week:
            in_month = d.month == month_num and d.year == year
            # Adjacent-month padding cells get no chips at all (TECH_PLAN cut).
            cells.append(
                {
                    "date": d,
                    "in_month": in_month,
                    "events": events_by_day.get(d, []) if in_month else [],
                    # One chip per PERSON: a person may hold overlapping approved
                    # requests, but the grid shows people (like the away board),
                    # not rows. Order is preserved (already platoon → name).
                    "off_leave": _dedupe_by_person(off_leave_by_day.get(d, [])) if in_month else [],
                }
            )
        weeks.append(cells)

    return {
        "month_start": month_start,
        "weekday_labels": list(stdlib_calendar.day_abbr),
        "weeks": weeks,
        "prev_ym": "%04d-%02d" % _adjacent_ym(year, month_num, -1),
        "next_ym": "%04d-%02d" % _adjacent_ym(year, month_num, 1),
        "today_ym": "%04d-%02d" % (today.year, today.month),
        "show_arctic": show_arctic,
        "off_leave_limit": OFF_LEAVE_CHIP_LIMIT,
    }
