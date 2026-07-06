"""Leave-vs-event clash detection. Pure: dates/day-parts turn into half-open
time windows, and two windows clash iff they strictly intersect — touching
endpoints (e.g. an AM off ending exactly when a PM event starts) are not a
clash, matching how the unit actually schedules back-to-back activities.
"""
from datetime import date, datetime, time, timedelta

from app.domain.types import DayPart

# Owner-confirmed 2026-07-06 (TECH_PLAN decision f): AM off covers up to
# 12:00, PM off starts at 12:00. Changing this needs a fresh owner sign-off.
DAY_PART_BOUNDARY = time(12, 0)


def day_part_window(start_date: date, end_date: date, day_part: DayPart) -> tuple[datetime, datetime]:
    """The half-open [start, end) window a leave request occupies.

    FULL spans the whole multi-day range. AM/PM are single-day by schema
    (the request form doesn't allow a half-day range), so `end_date` is
    ignored for them — the caller always passes start_date == end_date.
    AM starts at 00:00 and PM runs to the next midnight, not just the
    working hours either side of noon: the person is away for that entire
    half of the day from the unit's perspective, and the boundary only
    splits the working day, not their absence.
    """
    if day_part is DayPart.FULL:
        return (
            datetime.combine(start_date, time.min),
            datetime.combine(end_date + timedelta(days=1), time.min),
        )
    if day_part is DayPart.AM:
        return (
            datetime.combine(start_date, time.min),
            datetime.combine(start_date, DAY_PART_BOUNDARY),
        )
    return (
        datetime.combine(start_date, DAY_PART_BOUNDARY),
        datetime.combine(start_date + timedelta(days=1), time.min),
    )


def windows_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Strict half-open interval intersection; touching endpoints don't overlap."""
    return a_start < b_end and b_start < a_end


def leave_clashes_with_event(
    leave_start: date,
    leave_end: date,
    day_part: DayPart,
    event_start_dt: datetime,
    event_end_dt: datetime,
) -> bool:
    """True if the leave's day-part window strictly intersects the event's window.

    Takes plain dates/datetimes + DayPart (not model instances) so it stays
    pure and callable from anything — P2.8's service passes model fields in.
    """
    leave_window_start, leave_window_end = day_part_window(leave_start, leave_end, day_part)
    return windows_overlap(leave_window_start, leave_window_end, event_start_dt, event_end_dt)
