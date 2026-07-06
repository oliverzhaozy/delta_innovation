from datetime import date, datetime, time

from app.domain.clash import (
    DAY_PART_BOUNDARY,
    day_part_window,
    leave_clashes_with_event,
    windows_overlap,
)
from app.domain.types import DayPart


def test_day_part_boundary_is_noon():
    # Pins owner decision (f, 2026-07-06): changing this needs a fresh sign-off.
    assert DAY_PART_BOUNDARY == time(12, 0)


# --- day_part_window -----------------------------------------------------

def test_day_part_window_full_spans_whole_range():
    start, end = day_part_window(date(2026, 7, 6), date(2026, 7, 8), DayPart.FULL)
    assert start == datetime(2026, 7, 6, 0, 0)
    assert end == datetime(2026, 7, 9, 0, 0)


def test_day_part_window_am_is_morning_half():
    start, end = day_part_window(date(2026, 7, 6), date(2026, 7, 6), DayPart.AM)
    assert start == datetime(2026, 7, 6, 0, 0)
    assert end == datetime(2026, 7, 6, 12, 0)


def test_day_part_window_pm_is_afternoon_through_midnight():
    start, end = day_part_window(date(2026, 7, 6), date(2026, 7, 6), DayPart.PM)
    assert start == datetime(2026, 7, 6, 12, 0)
    assert end == datetime(2026, 7, 7, 0, 0)


# --- windows_overlap -------------------------------------------------------

def test_windows_overlap_strict_intersection():
    a_start, a_end = datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 11, 0)
    b_start, b_end = datetime(2026, 7, 6, 10, 0), datetime(2026, 7, 6, 12, 0)
    assert windows_overlap(a_start, a_end, b_start, b_end)


def test_windows_overlap_touching_endpoints_do_not_overlap():
    a_start, a_end = datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 12, 0)
    b_start, b_end = datetime(2026, 7, 6, 12, 0), datetime(2026, 7, 6, 15, 0)
    assert not windows_overlap(a_start, a_end, b_start, b_end)


def test_windows_overlap_disjoint():
    a_start, a_end = datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 10, 0)
    b_start, b_end = datetime(2026, 7, 6, 11, 0), datetime(2026, 7, 6, 12, 0)
    assert not windows_overlap(a_start, a_end, b_start, b_end)


# --- leave_clashes_with_event: done-criterion 1 (decision f's exact scenario) --

def test_am_off_vs_afternoon_conduct_is_no_clash():
    d = date(2026, 7, 6)
    assert not leave_clashes_with_event(
        d, d, DayPart.AM, datetime(2026, 7, 6, 14, 0), datetime(2026, 7, 6, 17, 0)
    )


def test_pm_off_vs_morning_conduct_is_no_clash():
    d = date(2026, 7, 6)
    assert not leave_clashes_with_event(
        d, d, DayPart.PM, datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 11, 0)
    )


# --- done-criterion 2: boundary touching is never a clash ------------------

def test_am_off_vs_event_starting_exactly_at_noon_is_no_clash():
    d = date(2026, 7, 6)
    assert not leave_clashes_with_event(
        d, d, DayPart.AM, datetime(2026, 7, 6, 12, 0), datetime(2026, 7, 6, 13, 0)
    )


def test_event_ending_exactly_at_noon_vs_pm_off_is_no_clash():
    d = date(2026, 7, 6)
    assert not leave_clashes_with_event(
        d, d, DayPart.PM, datetime(2026, 7, 6, 10, 0), datetime(2026, 7, 6, 12, 0)
    )


def test_event_ending_at_midnight_vs_full_day_starting_that_midnight_is_no_clash():
    # Event on 5 Jul ending exactly at the 6 Jul 00:00 boundary; FULL leave starts 6 Jul.
    leave_start = leave_end = date(2026, 7, 6)
    assert not leave_clashes_with_event(
        leave_start,
        leave_end,
        DayPart.FULL,
        datetime(2026, 7, 5, 20, 0),
        datetime(2026, 7, 6, 0, 0),
    )


# --- done-criterion 3: FULL day vs any overlapping event = clash -----------

def test_full_day_vs_morning_only_event_clashes():
    d = date(2026, 7, 6)
    assert leave_clashes_with_event(
        d, d, DayPart.FULL, datetime(2026, 7, 6, 8, 0), datetime(2026, 7, 6, 11, 0)
    )


def test_full_day_vs_evening_only_event_clashes():
    d = date(2026, 7, 6)
    assert leave_clashes_with_event(
        d, d, DayPart.FULL, datetime(2026, 7, 6, 19, 0), datetime(2026, 7, 6, 22, 0)
    )


def test_full_day_vs_event_fully_containing_the_leave_range_clashes():
    d = date(2026, 7, 6)
    assert leave_clashes_with_event(
        d, d, DayPart.FULL, datetime(2026, 7, 5, 6, 0), datetime(2026, 7, 8, 6, 0)
    )


# --- done-criterion 4: multi-day both sides --------------------------------

def test_multiday_full_leave_vs_event_overlapping_only_last_leave_day_clashes():
    leave_start, leave_end = date(2026, 7, 6), date(2026, 7, 8)
    # Event runs 8-9 Jul, overlapping only the last leave day (8 Jul).
    assert leave_clashes_with_event(
        leave_start,
        leave_end,
        DayPart.FULL,
        datetime(2026, 7, 8, 10, 0),
        datetime(2026, 7, 9, 10, 0),
    )


def test_multiday_full_leave_vs_event_shifted_entirely_after_is_no_clash():
    leave_start, leave_end = date(2026, 7, 6), date(2026, 7, 8)
    # Same event, shifted to start only once the leave's window has ended (9 Jul 00:00+).
    assert not leave_clashes_with_event(
        leave_start,
        leave_end,
        DayPart.FULL,
        datetime(2026, 7, 9, 10, 0),
        datetime(2026, 7, 10, 10, 0),
    )


# --- done-criterion 5: straddling the boundary clashes both halves ---------

def test_am_off_vs_event_straddling_boundary_clashes():
    d = date(2026, 7, 6)
    assert leave_clashes_with_event(
        d, d, DayPart.AM, datetime(2026, 7, 6, 11, 0), datetime(2026, 7, 6, 13, 0)
    )


def test_pm_off_vs_event_straddling_boundary_clashes():
    d = date(2026, 7, 6)
    assert leave_clashes_with_event(
        d, d, DayPart.PM, datetime(2026, 7, 6, 11, 0), datetime(2026, 7, 6, 13, 0)
    )
