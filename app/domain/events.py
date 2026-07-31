"""Pure event helpers (UI-9): per-calendar label resolution, the all-day time
convention and the day-detail panel's time line. No Flask/DB imports — pytest
exercises these without HTTP.
"""
from datetime import datetime, time

from app.domain.types import ArcticLabel, Calendar, TpLabel

# The panel's label for an entry that occupies a whole day. One constant, so an
# OFF/LEAVE line and an all-day event line can never read differently.
ALL_DAY_DISPLAY = "All-day"


def label_class_for(calendar):
    """The label enum owning `calendar`'s label set."""
    return ArcticLabel if calendar is Calendar.ARCTIC else TpLabel


def is_valid_label(calendar, value):
    """True if `value` is an allowed label for `calendar`. Empty/None is valid —
    labels are optional (owner decision UI-9)."""
    if not value:
        return True
    return value in {member.value for member in label_class_for(calendar)}


def all_day_bounds(start_date, end_date):
    """(start_dt, end_dt) for an all-day event spanning [start_date, end_date]
    inclusive: 00:00 on the first day to 23:59:59.999999 on the last.

    This is the ONE owner of the all-day time convention. Two invariants ride on
    it: end_dt > start_dt holds even for a single day (so the model's
    ck_event_dt_order never trips), and the month grid — which buckets by
    `.date()` — lands the event on exactly [start_date, end_date] and no day after.
    """
    return datetime.combine(start_date, time.min), datetime.combine(end_date, time.max)


def event_days(start_dt, end_dt):
    """(start_date, end_date) — the inclusive span of DATES an event covers.

    THE single owner of the times-ignored rule (owner decision 3, 2026-07-26): an
    event's clock times never narrow its day span, so a 23:00→01:00 event covers
    BOTH calendar days in full. Every consumer calls this instead of reaching for
    `.date()` itself, so a course cover and a course chip can never disagree on
    which days are covered.
    """
    return start_dt.date(), end_dt.date()


def is_all_day(start_dt, end_dt):
    """True if the event carries the `all_day_bounds` shape.

    There is no stored all-day flag — the times ARE the flag, so this is the one
    place the shape is recognised. Anything else is a timed event, including a
    00:00→23:00 one: it stops short of the convention's end instant.
    """
    return (start_dt, end_dt) == all_day_bounds(*event_days(start_dt, end_dt))


def _clock(moment):
    # 12-hour, no leading zero. Built by hand because `%-I` is a glibc extension
    # the Windows dev box does not have.
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def day_time_display(start_dt, end_dt, day):
    """The one-line time label the day-detail panel shows for `day`.

    `day` is one of the DATES the event covers (`event_days`). An all-day event
    reads "All-day" on every one of them, and so does any middle day of a timed
    multi-day event — a bar crossing a day occupies all of it. A timed event
    confined to one day shows both ends; the first and last day of a timed
    multi-day event show whichever end falls on them.
    """
    if is_all_day(start_dt, end_dt):
        return ALL_DAY_DISPLAY
    first, last = event_days(start_dt, end_dt)
    if first == last:
        return f"{_clock(start_dt)} – {_clock(end_dt)}"
    if day == first:
        return _clock(start_dt)
    if day == last:
        return _clock(end_dt)
    return ALL_DAY_DISPLAY
