"""Meal-indent presence counters (owner decision (j) 2026-07-07, revised by
decision (bb) 2026-07-29).

Indents cover every NSF always, plus the regulars who individually opt in
(`person.meals_opt_in`) — `_counted` below is the ONE owner of that predicate.
S4 needs two numbers per day D, both derived from the same parade documents
everyone else reads — never a second derivation:

    day_in_camp(D) = morning(D) PRESENT IN CAMP (current strength + others in
                     camp). Feeds the day's indent (lunch).
    overnight(D)   = roll_call(D+1) CURRENT STRENGTH (the night D -> D+1).
                     Feeds dinner(D) and breakfast(D+1) — indents are placed in
                     advance, so tonight's stayers ARE tomorrow's breakfast.

Decision (j) also removed the earlier per-meal compute with S4 manual
adjustments (P3b.5); `meal_adjustment` stays in the schema, dormant — dropping
a table is riskier than ignoring one. Pure module: stdlib + sibling app.domain
only.
"""
from dataclasses import dataclass

from app.domain.types import Service


@dataclass(frozen=True)
class MealPresence:
    """One day's two counters for the S4 page."""

    day_in_camp: int
    overnight: int

    @property
    def expected(self) -> int:
        # The one number the month grid indents for (decision (bb)): the larger
        # sitting feeds the smaller, so nobody goes without a meal.
        return max(self.day_in_camp, self.overnight)


def _counted(people) -> int:
    return sum(1 for p in people if p.service is Service.NSF or p.meals_opt_in)


def meal_presence(morning_doc, roll_call_next_doc) -> MealPresence:
    """Counters for day D from morning(D) and roll_call(D+1) — the caller
    (meal_service) builds both docs through parade_service.build_doc."""
    return MealPresence(
        day_in_camp=_counted(morning_doc.current_strength_people)
        + _counted(morning_doc.others_in_camp_people),
        overnight=_counted(roll_call_next_doc.current_strength_people),
    )
