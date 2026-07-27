from datetime import date

from app.domain.dates import format_ddmmyy_range, is_working_day, working_days


def test_weekend_days_do_not_count():
    # Fri 3 Jul – Mon 6 Jul 2026 spans a weekend: only Fri + Mon count.
    assert working_days(date(2026, 7, 3), date(2026, 7, 6)) == 2


def test_holidays_do_not_count():
    holidays = frozenset({date(2026, 7, 6)})
    assert working_days(date(2026, 7, 3), date(2026, 7, 6), holidays) == 1


def test_single_working_day():
    assert working_days(date(2026, 7, 8), date(2026, 7, 8)) == 1


def test_range_entirely_on_weekend_is_zero():
    assert working_days(date(2026, 7, 4), date(2026, 7, 5)) == 0


def test_is_working_day():
    assert is_working_day(date(2026, 7, 8))
    assert not is_working_day(date(2026, 7, 4))  # Saturday
    assert not is_working_day(date(2026, 7, 8), frozenset({date(2026, 7, 8)}))


def test_ddmmyy_range_spans_two_dates():
    assert format_ddmmyy_range(date(2026, 7, 27), date(2026, 7, 28)) == "270726 - 280726"


def test_ddmmyy_range_collapses_to_one_date():
    assert format_ddmmyy_range(date(2026, 7, 27), date(2026, 7, 27)) == "270726"


def test_ddmmyy_range_crosses_the_year():
    assert format_ddmmyy_range(date(2026, 12, 31), date(2027, 1, 1)) == "311226 - 010127"
