"""UI-9 pure-domain tests: all-day time bounds and per-calendar label rules,
plus the day-detail panel's time line (UI-24)."""
from datetime import date, datetime, time

from app.domain.events import (
    all_day_bounds,
    day_time_display,
    is_all_day,
    is_valid_label,
    label_class_for,
)
from app.domain.types import ArcticLabel, Calendar, TpLabel


# ---------- all_day_bounds ----------

def test_all_day_bounds_single_day_spans_midnight_to_end_of_day():
    start, end = all_day_bounds(date(2026, 7, 8), date(2026, 7, 8))
    assert start == datetime(2026, 7, 8, 0, 0)
    assert end == datetime(2026, 7, 8, 23, 59, 59, 999999)
    # The invariant every all-day event rides on: end > start even for one day,
    # so the model's ck_event_dt_order never trips.
    assert end > start


def test_all_day_bounds_multi_day_keeps_first_and_last_dates():
    start, end = all_day_bounds(date(2026, 7, 8), date(2026, 7, 10))
    assert start == datetime(2026, 7, 8, 0, 0)
    assert end.date() == date(2026, 7, 10)  # buckets onto the 10th, not the 11th
    assert end.time() == time.max


def test_all_day_bounds_across_month_and_year_rollover():
    start, end = all_day_bounds(date(2026, 12, 31), date(2027, 1, 2))
    assert start == datetime(2026, 12, 31, 0, 0)
    assert end == datetime(2027, 1, 2, 23, 59, 59, 999999)


# ---------- is_all_day ----------

def test_the_all_day_bounds_shape_is_what_makes_an_event_all_day():
    assert is_all_day(*all_day_bounds(date(2026, 7, 8), date(2026, 7, 8)))
    assert is_all_day(*all_day_bounds(date(2026, 7, 8), date(2026, 7, 10)))


def test_a_timed_event_is_not_all_day_even_when_it_covers_the_whole_day():
    assert not is_all_day(datetime(2026, 7, 8, 8, 0), datetime(2026, 7, 8, 17, 0))
    # Midnight to 23:00 stops short of the convention's end instant.
    assert not is_all_day(datetime(2026, 7, 8, 0, 0), datetime(2026, 7, 8, 23, 0))


# ---------- day_time_display ----------

def test_an_all_day_event_reads_all_day_on_every_day_it_covers():
    start, end = all_day_bounds(date(2026, 7, 8), date(2026, 7, 10))
    for day in (date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10)):
        assert day_time_display(start, end, day) == "All-day"


def test_a_single_day_timed_event_shows_both_ends():
    display = day_time_display(
        datetime(2026, 7, 8, 9, 0), datetime(2026, 7, 8, 17, 30), date(2026, 7, 8)
    )
    assert display == "9:00 AM – 5:30 PM"


def test_the_twelve_hour_clock_has_no_leading_zero_and_no_zero_hour():
    # 00:05 is 12:05 AM and 12:05 is 12:05 PM — the two cases `hour % 12` alone
    # gets wrong.
    assert day_time_display(
        datetime(2026, 7, 8, 0, 5), datetime(2026, 7, 8, 12, 5), date(2026, 7, 8)
    ) == "12:05 AM – 12:05 PM"


def test_a_timed_multi_day_event_shows_the_end_that_falls_on_the_day():
    start, end = datetime(2026, 7, 6, 7, 0), datetime(2026, 7, 8, 15, 0)
    assert day_time_display(start, end, date(2026, 7, 6)) == "7:00 AM"
    assert day_time_display(start, end, date(2026, 7, 7)) == "All-day"
    assert day_time_display(start, end, date(2026, 7, 8)) == "3:00 PM"


# ---------- label_class_for / is_valid_label ----------

def test_label_class_for_maps_each_calendar_to_its_enum():
    assert label_class_for(Calendar.TP) is TpLabel
    assert label_class_for(Calendar.ARCTIC) is ArcticLabel


def test_valid_label_accepts_own_calendar_and_rejects_the_other():
    assert is_valid_label(Calendar.TP, TpLabel.PT.value)
    assert is_valid_label(Calendar.ARCTIC, ArcticLabel.CONDUCTS.value)
    # A TP label on an ARCTIC event (and vice versa) is rejected.
    assert not is_valid_label(Calendar.ARCTIC, TpLabel.PT.value)
    assert not is_valid_label(Calendar.TP, ArcticLabel.CONDUCTS.value)


def test_empty_label_is_valid_because_labels_are_optional():
    assert is_valid_label(Calendar.TP, "")
    assert is_valid_label(Calendar.TP, None)
    assert is_valid_label(Calendar.ARCTIC, "")


def test_unknown_label_is_rejected():
    assert not is_valid_label(Calendar.TP, "Nonsense")
    assert not is_valid_label(Calendar.ARCTIC, "Nonsense")


# ---------- slug uniqueness (colour-class keys) ----------

def test_every_label_slug_is_unique_across_both_calendars():
    slugs = [m.slug for m in TpLabel] + [m.slug for m in ArcticLabel]
    assert len(slugs) == len(set(slugs))


def test_slug_is_css_safe_and_calendar_prefixed():
    assert TpLabel.MPT_PMCS_EAS.slug == "tp-mpt-pmcs-eas"
    assert ArcticLabel.OPS_OPS_RELATED.slug == "arctic-ops-ops-related"
    assert TpLabel.ON_COURSE.slug == "tp-on-course"  # keys .ev-tp-on-course
    for slug in [m.slug for m in TpLabel] + [m.slug for m in ArcticLabel]:
        assert slug.replace("-", "").isalnum()


# ---------- value distinctness across the two calendars ----------

def test_every_label_value_is_distinct_across_both_calendars():
    """A stored label string must map to exactly one calendar: `is_valid_label`
    accepts a value per calendar, the event form renders ONE <select> over both
    enums, and its JS maps value -> owning calendar. A value in both enums would
    make all three ambiguous. This is why TpLabel.ON_COURSE is "Course" and not
    "On Course" — ArcticLabel.ON_COURSE already owns that string."""
    values = [m.value for m in TpLabel] + [m.value for m in ArcticLabel]
    assert len(values) == len(set(values))
    assert TpLabel.ON_COURSE.value == "Course"
    assert ArcticLabel.ON_COURSE.value == "On Course"
    assert not is_valid_label(Calendar.ARCTIC, TpLabel.ON_COURSE.value)
    assert not is_valid_label(Calendar.TP, ArcticLabel.ON_COURSE.value)
