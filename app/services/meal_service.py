"""Meal-indent counters for the S4 page (owner decision (j) 2026-07-07,
revised by (bb) 2026-07-29): derive morning(D) and roll_call(D+1) through
parade_service.build_doc — the ONE document pipeline (pre-flight addendum A2),
so the counters can never disagree with the parade pages — and hand both docs
to the pure domain compute.
"""
import calendar as stdlib_calendar
from datetime import date, timedelta

from app.domain import meals as meals_domain
from app.domain.dates import adjacent_ym, parse_ym, today_sgt
from app.domain.types import ParadeVariant
from app.services import parade_service


def compute_for(day):
    """(MealPresence, imbalance) for day D. If either doc is refused by the
    engine the counters are refused too — a wrong indent number is worse than
    none (same posture as the parade pages)."""
    morning = parade_service.build_doc(day, ParadeVariant.MORNING)
    rc_next = parade_service.build_doc(day + timedelta(days=1), ParadeVariant.ROLL_CALL)
    imbalance = morning.imbalance or rc_next.imbalance
    if imbalance:
        return None, imbalance
    return meals_domain.meal_presence(morning.doc, rc_next.doc), None


def month_context(ym_raw):
    """Template context for the meal-indent month grid — one expected number
    per in-month day, `None` where that day's documents are out of balance so
    one refused day shows "—" instead of hiding the whole month.

    ~62 build_doc calls per view at 36 people; deliberately uncached — this app
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
            expected = None
            if in_month:
                counts, imbalance = compute_for(day)
                expected = None if imbalance else counts.expected
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
