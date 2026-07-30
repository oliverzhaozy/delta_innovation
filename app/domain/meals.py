"""Meal-indent day counter (owner decision (j) 2026-07-07, revised by (bb)
2026-07-29 and again by (cc) 2026-07-30).

Indents cover every NSF always, plus the regulars who individually opt in
(`person.meals_opt_in`) — `_counted` below is the ONE owner of that predicate.
S4 needs ONE number per day D, derived from the same parade document everyone
else reads — never a second derivation:

    day_in_camp(D) = morning(D) PRESENT IN CAMP (current strength + others in
                     camp). That count IS the day's indent.

Decision (cc) removed the second counter that read roll_call(D+1), and with it
the max() rule: S4 indents off the day's parade, so a night-heavier day
under-indents — the owner accepted that.

Decision (j) also removed the earlier per-meal compute with S4 manual
adjustments (P3b.5); `meal_adjustment` stays in the schema, dormant — dropping
a table is riskier than ignoring one. Pure module: stdlib + sibling app.domain
only.
"""
from app.domain.types import Service


def _counted(people) -> int:
    return sum(1 for p in people if p.service is Service.NSF or p.meals_opt_in)


def day_in_camp(morning_doc) -> int:
    """The indent for day D: morning(D) PRESENT IN CAMP, counted people only.
    The caller (meal_service) builds the doc through parade_service.build_doc."""
    return (
        _counted(morning_doc.current_strength_people)
        + _counted(morning_doc.others_in_camp_people)
    )
