"""UI-9 pure-domain tests: all-day time bounds and per-calendar label rules."""
from datetime import date, datetime, time

from app.domain.events import all_day_bounds, is_valid_label, label_class_for
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
    for slug in [m.slug for m in TpLabel] + [m.slug for m in ArcticLabel]:
        assert slug.replace("-", "").isalnum()
