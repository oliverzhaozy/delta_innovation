"""Per-meal in-camp counts (P3b.5). Pure: stdlib + sibling app.domain modules
only, so the meal <-> parade-category mapping and the adjustment arithmetic are
testable without an app or a DB. The route (P3b.6) builds the three parade docs
and sums the MealAdjustment rows; this module never touches Flask or the DB.

Meal <-> document mapping (the CONTROLLER-CORRECTED offsets — the plan line was
off by one against docs/PARADE_FORMATS' labeling convention, where the roll call
LABELED D covers the night D-1 -> D):

    breakfast(D) = roll_call(D)   CURRENT STRENGTH + duty   (last night's stayers)
    lunch(D)     = morning(D)     PRESENT IN CAMP (A + K)    (in camp by day)
    dinner(D)    = roll_call(D+1) CURRENT STRENGTH          (tonight's stayers;
                                                             stay-outs book out
                                                             before dinner)

Duty personnel eat breakfast regardless of stay-out; duty assignment does not
exist until P4, so it is an explicit `+ 0` term (a named hook, never a faked
number). The NSF sub-count per meal is the base people whose service is NSF.
Adjustments are applied LAST, as a coarse ± on the headcount: a negative final
is carried as-is with a `negative` flag, never clamped — a wrong-looking number
the S4 can see and fix beats one silently floored to zero.
"""
from dataclasses import dataclass

from app.domain.types import Meal, Service


@dataclass(frozen=True)
class MealCount:
    """One meal's decision-support line: the derived base (all people + the NSF
    sub-set), the manual adjustment, and the final total after it.

    `final_total = base_total + adjustment_delta`. `negative` is set when that
    goes below zero and the value is kept, not floored (see module docstring).
    """

    meal: Meal
    base_total: int
    base_nsf: int
    adjustment_delta: int
    final_total: int
    negative: bool


def _nsf(people) -> int:
    # NSF sub-count: how many of the derived base are NSF (vs regulars).
    return sum(1 for p in people if p.service is Service.NSF)


def _count(meal, base_people, adjustments) -> MealCount:
    base_total = len(base_people)
    delta = adjustments.get(meal, 0)  # pre-summed per-meal ±, 0 if none keyed
    final_total = base_total + delta  # adjustment applied last
    return MealCount(
        meal=meal,
        base_total=base_total,
        base_nsf=_nsf(base_people),
        adjustment_delta=delta,
        final_total=final_total,
        negative=final_total < 0,
    )


def compute_meals(day, roll_call_doc_today, morning_doc, roll_call_doc_next, adjustments):
    """Per-meal counts for `day` (D) from three already-built parade docs.

    `roll_call_doc_today` is roll_call(D), `morning_doc` is morning(D),
    `roll_call_doc_next` is roll_call(D+1) — the caller (P3b.6 route) resolves
    the roster for D and D+1 and categorizes them. `adjustments` is a
    `{Meal: int}` of pre-summed per-meal deltas (the pure module never sees the
    DB rows). `day` anchors the result to a calendar date for the caller/logging;
    the arithmetic reads it off the docs, so it is not otherwise used here.

    Returns `{Meal: MealCount}` for all three meals.
    """
    breakfast_people = (
        # roll_call(D) CURRENT STRENGTH (last night's stayers)
        list(roll_call_doc_today.current_strength_people)
        # + duty personnel — P4 hook: duty personnel eat breakfast regardless of
        # stay-out. duty_assignment does not exist yet, so this contributes 0.
        + []
    )
    lunch_people = (
        # morning(D) PRESENT IN CAMP = CURRENT STRENGTH (A) + OTHERS IN CAMP (K)
        list(morning_doc.current_strength_people)
        + list(morning_doc.others_in_camp_people)
    )
    dinner_people = list(roll_call_doc_next.current_strength_people)

    return {
        Meal.BREAKFAST: _count(Meal.BREAKFAST, breakfast_people, adjustments),
        Meal.LUNCH: _count(Meal.LUNCH, lunch_people, adjustments),
        Meal.DINNER: _count(Meal.DINNER, dinner_people, adjustments),
    }
