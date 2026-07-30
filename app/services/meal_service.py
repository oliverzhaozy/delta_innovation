"""Meal-indent day counter for the S4 page (owner decision (j) 2026-07-07,
revised by (bb) 2026-07-29 and (cc) 2026-07-30): derive morning(D) through
parade_service.build_doc — the ONE document pipeline (pre-flight addendum A2),
so the count can never disagree with the parade pages — and hand the doc to the
pure domain compute.
"""
import calendar as stdlib_calendar
from datetime import date

from app.domain import meals as meals_domain
from app.domain.dates import adjacent_ym, parse_ym, today_sgt
from app.domain.types import ParadeVariant
from app.services import parade_service


def compute_for(day):
    """(expected, imbalance) for day D. If the document is refused by the
    engine the count is refused too — a wrong indent number is worse than
    none (same posture as the parade pages)."""
    morning = parade_service.build_doc(day, ParadeVariant.MORNING)
    if morning.imbalance:
        return None, morning.imbalance
    return meals_domain.day_in_camp(morning.doc), None


def month_context(ym_raw):
    """Template context for the meal-indent month grid — one expected number
    per in-month day, `None` where that day's document is out of balance so
    one refused day shows "—" instead of hiding the whole month.

    ~31 build_doc calls per view at 36 people; deliberately uncached — this app
    has no cache layer by rule, and the page is S4-only and infrequent.
    """
    today = today_sgt()
    year, month_num = parse_ym(ym_raw)
    weeks = []
    for week in stdlib_calendar.Calendar(firstweekday=0).monthdatescalendar(year, month_num):
        cells = []
        for day in week:
            # Adjacent-month padding cells carry no number (same cut as the
            # calendar grid) — and cost no build_doc.
            in_month = day.month == month_num and day.year == year
            expected = compute_for(day)[0] if in_month else None
            cells.append({"date": day, "in_month": in_month, "expected": expected})
        weeks.append(cells)
    return {
        "month_start": date(year, month_num, 1),
        "weekday_labels": list(stdlib_calendar.day_abbr),
        "weeks": weeks,
        "prev_ym": "%04d-%02d" % adjacent_ym(year, month_num, -1),
        "next_ym": "%04d-%02d" % adjacent_ym(year, month_num, 1),
        "today_ym": "%04d-%02d" % (today.year, today.month),
        "today": today,
    }
