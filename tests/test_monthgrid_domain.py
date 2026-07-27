"""Pure tests for the month-grid geometry (UI-23) — no app, no HTTP.

A month grid draws ONE bar per event/off-run per week row, so three pieces of
arithmetic have to be right: which days merge into a run, which columns a run
occupies on a given week, and which lane the bar lands on.
"""
from datetime import date, timedelta

from app.domain.monthgrid import merge_off_runs, overflow_by_column, pack_lanes, week_segment
from app.domain.types import DayPart


class Row:
    """Stand-in for a presence_service AbsenceRow: the merge key plus identity."""

    def __init__(self, person_id, label="OFF", day_part=DayPart.FULL):
        self.person_id = person_id
        self.label = label
        self.day_part = day_part


def days(first, count):
    return [first + timedelta(days=i) for i in range(count)]


def week_of(first, *, in_month_days=None):
    """7 (date, in_month) pairs starting at `first`; every day is in-month
    unless `in_month_days` names the subset that is."""
    return [
        (day, True if in_month_days is None else day in in_month_days)
        for day in days(first, 7)
    ]


# ---------- run merging ----------

def test_consecutive_identical_days_merge_into_one_run():
    rows_by_day = {day: [Row(1)] for day in days(date(2026, 7, 6), 4)}
    runs = merge_off_runs(rows_by_day)
    assert len(runs) == 1
    assert (runs[0].start, runs[0].end) == (date(2026, 7, 6), date(2026, 7, 9))


def test_a_gap_day_breaks_the_run():
    rows_by_day = {
        date(2026, 7, 6): [Row(1)],
        date(2026, 7, 7): [Row(1)],
        date(2026, 7, 8): [],
        date(2026, 7, 9): [Row(1)],
    }
    runs = merge_off_runs(rows_by_day)
    assert [(r.start, r.end) for r in runs] == [
        (date(2026, 7, 6), date(2026, 7, 7)),
        (date(2026, 7, 9), date(2026, 7, 9)),
    ]


def test_a_label_change_breaks_the_run():
    rows_by_day = {
        date(2026, 7, 6): [Row(1, label="OFF")],
        date(2026, 7, 7): [Row(1, label="LL")],
    }
    runs = merge_off_runs(rows_by_day)
    assert [(r.row.label, r.start, r.end) for r in runs] == [
        ("OFF", date(2026, 7, 6), date(2026, 7, 6)),
        ("LL", date(2026, 7, 7), date(2026, 7, 7)),
    ]


def test_two_people_never_merge_into_one_run():
    rows_by_day = {day: [Row(1), Row(2)] for day in days(date(2026, 7, 6), 2)}
    runs = merge_off_runs(rows_by_day)
    assert len(runs) == 2
    assert [r.row.person_id for r in runs] == [1, 2]  # input order preserved
    assert all((r.start, r.end) == (date(2026, 7, 6), date(2026, 7, 7)) for r in runs)


def test_day_part_change_breaks_the_run_and_the_run_keeps_its_day_part():
    rows_by_day = {
        date(2026, 7, 6): [Row(1, day_part=DayPart.AM)],
        date(2026, 7, 7): [Row(1, day_part=DayPart.FULL)],
        date(2026, 7, 8): [Row(1, day_part=DayPart.FULL)],
    }
    runs = merge_off_runs(rows_by_day)
    assert [(r.row.day_part, r.start, r.end) for r in runs] == [
        (DayPart.AM, date(2026, 7, 6), date(2026, 7, 6)),
        (DayPart.FULL, date(2026, 7, 7), date(2026, 7, 8)),
    ]


# ---------- week segmentation ----------

def test_mid_week_interval_spans_its_columns_without_clipping():
    segment = week_segment(
        start=date(2026, 7, 7), end=date(2026, 7, 9), week_days=week_of(date(2026, 7, 6))
    )
    assert (segment.col, segment.span) == (2, 3)
    assert not segment.clip_left and not segment.clip_right


def test_interval_crossing_a_week_boundary_clips_on_both_rows():
    first = week_segment(
        start=date(2026, 7, 6), end=date(2026, 7, 15), week_days=week_of(date(2026, 7, 6))
    )
    assert (first.col, first.span) == (1, 7)
    assert not first.clip_left and first.clip_right

    second = week_segment(
        start=date(2026, 7, 6), end=date(2026, 7, 15), week_days=week_of(date(2026, 7, 13))
    )
    assert (second.col, second.span) == (1, 3)
    assert second.clip_left and not second.clip_right


def test_padding_cells_of_an_adjacent_month_carry_no_bar():
    # The August grid opens on Mon 27 Jul; only Sat 1 / Sun 2 Aug are in-month,
    # so an interval clipped to August starts in column 6.
    week = week_of(date(2026, 7, 27), in_month_days={date(2026, 8, 1), date(2026, 8, 2)})
    segment = week_segment(start=date(2026, 8, 1), end=date(2026, 8, 2), week_days=week)
    assert (segment.col, segment.span) == (6, 2)


def test_interval_missing_the_weeks_in_month_days_returns_no_segment():
    week = week_of(date(2026, 6, 29), in_month_days=set(days(date(2026, 7, 1), 5)))
    assert week_segment(start=date(2026, 6, 29), end=date(2026, 6, 30), week_days=week) is None


# ---------- lane packing ----------

def test_disjoint_bars_share_the_top_lane():
    assert pack_lanes([(1, 2), (4, 2), (6, 1)]) == [0, 0, 0]


def test_overlapping_bars_step_down_a_lane_each():
    assert pack_lanes([(1, 3), (2, 3), (3, 3)]) == [0, 1, 2]


def test_the_longer_bar_wins_the_top_lane_at_an_equal_start():
    # Sorted by (col, -span): the 4-day bar is placed first even though the
    # 1-day bar came first in the input.
    assert pack_lanes([(2, 1), (2, 4)]) == [1, 0]


def test_a_bar_reuses_a_lane_freed_earlier_in_the_week():
    # (1,2) and (3,2) are disjoint, so both sit on lane 0 under the (1,5) bar.
    assert pack_lanes([(1, 5), (1, 2), (3, 2)]) == [0, 1, 1]


# ---------- the capped OFF/LEAVE band ----------

def test_four_concurrent_runs_show_three_bars_and_count_the_rest_per_day():
    placements = [(2, 3), (2, 3), (2, 3), (2, 3)]
    lanes = pack_lanes(placements)
    assert lanes == [0, 1, 2, 3]
    shown = [lane for lane in lanes if lane < 3]
    assert len(shown) == 3
    # The dropped run covered columns 2-4, so each of those days hides one.
    assert overflow_by_column(placements, lanes, lane_limit=3) == {2: 1, 3: 1, 4: 1}


def test_nothing_overflows_while_the_band_fits():
    placements = [(1, 1), (1, 1), (1, 1)]
    lanes = pack_lanes(placements)
    assert overflow_by_column(placements, lanes, lane_limit=3) == {}
