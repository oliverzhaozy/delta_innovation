"""NSF presence counters for meal indents (owner decision (j), 2026-07-07).

All meal indents are NSF-only, so S4 needs exactly two numbers per day D, both
derived from the same parade documents everyone else reads — never a second
derivation:

    day_in_camp(D) = morning(D) PRESENT IN CAMP (current strength + others in
                     camp), NSFs only. Feeds the day's indent (lunch).
    overnight(D)   = roll_call(D+1) CURRENT STRENGTH (the night D -> D+1),
                     NSFs only. Feeds dinner(D) and breakfast(D+1) — indents
                     are placed in advance, so tonight's stayers ARE tomorrow's
                     breakfast.

Regulars are never counted: they are excluded by service, not by presence.
Decision (j) also removed the earlier per-meal compute with S4 manual
adjustments (P3b.5); `meal_adjustment` stays in the schema, dormant — dropping
a table is riskier than ignoring one. Pure module: stdlib + sibling app.domain
only.
"""
from dataclasses import dataclass

from app.domain.types import Service


@dataclass(frozen=True)
class NsfPresence:
    """One day's two counters for the S4 page."""

    day_in_camp: int
    overnight: int


def _nsf(people) -> int:
    return sum(1 for p in people if p.service is Service.NSF)


def nsf_presence(morning_doc, roll_call_next_doc) -> NsfPresence:
    """Counters for day D from morning(D) and roll_call(D+1) — the caller
    (meal_service) builds both docs through parade_service.build_doc."""
    return NsfPresence(
        day_in_camp=_nsf(morning_doc.current_strength_people)
        + _nsf(morning_doc.others_in_camp_people),
        overnight=_nsf(roll_call_next_doc.current_strength_people),
    )
