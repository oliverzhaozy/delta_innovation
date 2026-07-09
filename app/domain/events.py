"""Pure event helpers (UI-9): per-calendar label resolution and the all-day
time convention. No Flask/DB imports — pytest exercises these without HTTP.
"""
from datetime import datetime, time

from app.domain.types import ArcticLabel, Calendar, TpLabel


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
