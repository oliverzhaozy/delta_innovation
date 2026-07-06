"""P3b.5 — meals compute (pure domain/meals.py) + the ParadeDoc person-list
extension that makes it possible.

Pure unit tests with duck-typed fakes (same style as test_roll_call /
test_morning_parade): no app, no DB. The fixture-week docs are built by driving
the REAL presence `resolve()` and `categorize()`, so the meal <-> document
mapping is proven honestly against the engine, never asserted by fiat. Every
expectation below was hand-derived from the corrected offsets (see the module
comment in app/domain/meals.py).
"""
import ast
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain import meals, parade
from app.domain.meals import compute_meals
from app.domain.presence import PresenceState, Resolution, resolve
from app.domain.types import (
    DayPart, DirectAbsenceType, LeaveType, Meal, Service, StatusType,
)

D = date(2026, 7, 6)      # the day meals are computed for
NEXT = D + timedelta(days=1)
DAY = D                   # alias used by the parade-people section


# --- duck-typed fakes ----------------------------------------------------

def person(display_name, *, service=Service.NSF, stay_out=False, is_active=True, id):
    # resolve() reads service/stay_out/is_active; parade_line reads display_name;
    # the NSF sub-count and person-identity dedup read service and id.
    return SimpleNamespace(
        id=id, display_name=display_name, service=service,
        stay_out=stay_out, is_active=is_active,
    )


def leave_row(type, start=D, end=D, day_part=DayPart.FULL):
    return SimpleNamespace(type=type, start_date=start, end_date=end, day_part=day_part)


def direct_row(type, start=D, end=D, day_part=DayPart.FULL):
    return SimpleNamespace(type=type, start_date=start, end_date=end, day_part=day_part)


def status_row(type, start=D, end=D, *, in_camp=False, day_part=DayPart.FULL, remarks=None):
    return SimpleNamespace(
        type=type, start_date=start, end_date=end,
        in_camp=in_camp, day_part=day_part, remarks=remarks,
    )


def absent(row):
    return Resolution(state=PresenceState.ABSENT, row=row)


def present(in_camp_rows=()):
    return Resolution(state=PresenceState.PRESENT, in_camp_rows=tuple(in_camp_rows))


def stay_out(in_camp_rows=()):
    return Resolution(state=PresenceState.STAY_OUT, in_camp_rows=tuple(in_camp_rows))


# =========================================================================
# ParadeDoc person-list extension (P3b.5 prerequisite)
# =========================================================================
#
# Each category now carries a parallel tuple of PERSON objects alongside its
# rendered lines. The renderers still read only the line tuples, so every
# existing golden stays byte-identical (its test file is UNMODIFIED); meals
# read the person tuples.

def test_person_lists_populated_parallel_for_every_morning_category():
    p1 = person("CPT Alpha", id=1)
    p2 = person("MSG Bravo", id=2)
    p3 = person("CPL Charlie", id=3)
    p4 = person("CFC Delta", id=4)
    p5 = person("3SG Echo", id=5)
    p6 = person("3SG Foxtrot", id=6)
    p7 = person("3SG Golf", id=7)
    p8 = person("3SG Hotel", id=8)
    pairs = [
        (p1, stay_out()),                                   # → CURRENT STRENGTH
        (p2, present()),                                    # → CURRENT STRENGTH
        (p3, absent(leave_row(LeaveType.LL))),             # → LEAVE
        (p4, absent(leave_row(LeaveType.OFF))),            # → OFF/OIL
        (p5, absent(status_row(StatusType.MC))),           # → MC
        (p6, present(in_camp_rows=[status_row(StatusType.OTHER, remarks="BDO")])),  # → OTHERS IN CAMP
        (p7, absent(status_row(StatusType.COURSE))),       # → ON COURSE
        (p8, absent(direct_row(DirectAbsenceType.OTHER))), # → OTHERS
    ]
    doc = parade.categorize(DAY, pairs, "morning")

    # Person tuple parallels the line tuple, category by category.
    assert doc.current_strength_people == (p1, p2)
    assert doc.leave_people == (p3,)
    assert doc.off_oil_people == (p4,)
    assert doc.mc_people == (p5,)
    assert doc.others_in_camp_people == (p6,)
    assert doc.on_course_people == (p7,)
    assert doc.others_people == (p8,)

    # The invariant: every category has as many people as lines, and each
    # person's parade_line is the head of the matching rendered line.
    categories = (
        "current_strength", "others_in_camp", "leave", "off_oil",
        "on_course", "mc", "others", "stay_out",
    )
    for name in categories:
        lines = getattr(doc, name)
        people = getattr(doc, f"{name}_people")
        assert len(lines) == len(people)
        for line, pers in zip(lines, people):
            assert line == parade.parade_line(pers) or line.startswith(
                parade.parade_line(pers) + " ("
            )


def test_person_lists_populated_for_roll_call_stay_out():
    p1 = person("CPT Alpha", id=1)
    p2 = person("MSG Bravo", id=2)
    doc = parade.categorize(DAY, [(p1, stay_out()), (p2, present())], "roll_call")
    assert doc.stay_out_people == (p1,)
    assert doc.current_strength_people == (p2,)


def test_two_distinct_people_with_identical_rank_name_do_not_raise():
    # Closes a ledgered P3a.6 minor: identical rendered lines used to trip the
    # rendered-line dedup. Person-identity (id) dedup lets two real people who
    # happen to share rank+name both stand.
    p1 = person("3SG John Tan", id=1)
    p2 = person("3SG John Tan", id=2)
    doc = parade.categorize(DAY, [(p1, present()), (p2, present())], "morning")  # no raise
    assert doc.current_strength == ("3SG JOHN TAN", "3SG JOHN TAN")
    assert doc.current_strength_people == (p1, p2)
    assert doc.validate() is doc


def test_validate_still_catches_the_same_person_in_two_categories():
    # The at-most-once guarantee is now keyed on id: the SAME person in two
    # categories (count still balances) must raise.
    p = person("3SG Same Person", id=1)
    doc = parade.ParadeDoc(
        day=DAY, variant="morning", total=2,
        current_strength=("3SG SAME PERSON",), current_strength_people=(p,),
        leave=("3SG SAME PERSON",), leave_people=(p,),
    )
    with pytest.raises(parade.ParadeImbalance):
        doc.validate()


# =========================================================================
# Meal enum
# =========================================================================

def test_meal_enum_members_and_labels():
    assert [m.value for m in Meal] == ["BREAKFAST", "LUNCH", "DINNER"]
    assert Meal.BREAKFAST.label == "Breakfast"
    assert Meal.LUNCH.label == "Lunch"
    assert Meal.DINNER.label == "Dinner"


# =========================================================================
# Fixture week — meal membership by persona (done-criterion 2)
# =========================================================================
#
# Roster (each row carries the rows fed to resolve() for BOTH D and D+1):
#   A  stay-out NSF          — books out every night
#   B  stay-in NSF           — present around the clock
#   C  MC NSF                — MC covering D-2..D+3 (covers D and D+1)
#   E  PM-off stay-in NSF    — OFF, PM day-part, single day D only
#   F  regular (stay-out)    — regulars default to stay-out
#
# The three documents that feed the three meals (corrected offsets):
#   breakfast(D) = roll_call(D)   CURRENT STRENGTH   (last night's stayers)
#   lunch(D)     = morning(D)     PRESENT IN CAMP     (A + K)
#   dinner(D)    = roll_call(D+1) CURRENT STRENGTH    (tonight's stayers)

A = person("3SG Stayout Nsf", service=Service.NSF, stay_out=True, id=1)
B = person("3SG Stayin Nsf", service=Service.NSF, stay_out=False, id=2)
C = person("3SG Mc Nsf", service=Service.NSF, stay_out=False, id=3)
E = person("3SG Pmoff Nsf", service=Service.NSF, stay_out=False, id=4)
F = person("CPT Regular Guy", service=Service.REGULAR, stay_out=False, id=5)

ROSTER = [A, B, C, E, F]
ROWS = {
    A.id: {},
    B.id: {},
    C.id: {"statuses": [status_row(StatusType.MC, start=D - timedelta(days=2),
                                   end=D + timedelta(days=3), in_camp=False)]},
    E.id: {"leaves": [leave_row(LeaveType.OFF, start=D, end=D, day_part=DayPart.PM)]},
    F.id: {},
}


def _pairs_for(day):
    return [(p, resolve(p, day, **ROWS[p.id])) for p in ROSTER]


def _build_docs():
    roll_today = parade.categorize(D, _pairs_for(D), "roll_call")
    morning = parade.categorize(D, _pairs_for(D), "morning")
    roll_next = parade.categorize(NEXT, _pairs_for(NEXT), "roll_call")
    return roll_today, morning, roll_next


# Meal -> the person tuple that feeds it, mirrored independently from the docs
# (NOT from compute_meals' own arithmetic), so membership is checked honestly.
def _breakfast_people(roll_today, morning, roll_next):
    return roll_today.current_strength_people          # + duty (P4 hook, 0 today)


def _lunch_people(roll_today, morning, roll_next):
    return morning.current_strength_people + morning.others_in_camp_people


def _dinner_people(roll_today, morning, roll_next):
    return roll_next.current_strength_people


def test_stay_out_nsf_is_in_lunch_only():
    docs = _build_docs()
    assert A not in _breakfast_people(*docs)   # books out — not an overnight stayer
    assert A in _lunch_people(*docs)           # back for the day (STAY OUT dissolves)
    assert A not in _dinner_people(*docs)      # books out again before dinner


def test_stay_in_nsf_is_in_all_three_meals():
    docs = _build_docs()
    assert B in _breakfast_people(*docs)
    assert B in _lunch_people(*docs)
    assert B in _dinner_people(*docs)


def test_mc_person_is_in_no_meal():
    docs = _build_docs()
    assert C not in _breakfast_people(*docs)
    assert C not in _lunch_people(*docs)
    assert C not in _dinner_people(*docs)


def test_pm_off_person_is_in_all_three_meals_derived_from_the_engine():
    # DERIVED, not assumed (done-criterion 2). A PM-off is present at
    # roll_call(D) and morning(D) -> breakfast + lunch. Dinner "depends on
    # coverage" of roll_call(D+1): a PM half-day is single-day (D only), so it
    # does NOT cover D+1; resolve(E, D+1) sees no covering row -> PRESENT -> in
    # CURRENT STRENGTH -> in dinner. Owner decision (c) agrees: PM-off is away
    # in the afternoon only and expected back at night, so they eat dinner. The
    # naive "PM-off not in dinner" does NOT match the engine.
    docs = _build_docs()
    assert E in _breakfast_people(*docs)
    assert E in _lunch_people(*docs)
    assert E in _dinner_people(*docs)


def test_regular_is_in_lunch_only_and_excluded_from_the_nsf_subcount():
    docs = _build_docs()
    assert F not in _breakfast_people(*docs)
    assert F in _lunch_people(*docs)
    assert F not in _dinner_people(*docs)


# --- the counts these memberships imply (base_total + NSF sub-count) --------

def test_fixture_week_base_totals_and_nsf_subcounts():
    roll_today, morning, roll_next = _build_docs()
    counts = compute_meals(D, roll_today, morning, roll_next, {})

    # breakfast: {B, E} — both NSF
    assert counts[Meal.BREAKFAST].base_total == 2
    assert counts[Meal.BREAKFAST].base_nsf == 2
    # lunch: {A, B, E, F} — F is a regular, so 3 of 4 are NSF
    assert counts[Meal.LUNCH].base_total == 4
    assert counts[Meal.LUNCH].base_nsf == 3
    # dinner: {B, E} — both NSF
    assert counts[Meal.DINNER].base_total == 2
    assert counts[Meal.DINNER].base_nsf == 2


def test_breakfast_duty_hook_adds_zero_today():
    # breakfast = roll_call(D) CURRENT STRENGTH + duty personnel. Duty is a P4
    # hook that contributes an explicit 0 today, so the base equals CURRENT
    # STRENGTH exactly.
    roll_today, morning, roll_next = _build_docs()
    counts = compute_meals(D, roll_today, morning, roll_next, {})
    assert counts[Meal.BREAKFAST].base_total == len(roll_today.current_strength_people)


def test_meal_count_returns_all_three_meals():
    roll_today, morning, roll_next = _build_docs()
    counts = compute_meals(D, roll_today, morning, roll_next, {})
    assert set(counts) == {Meal.BREAKFAST, Meal.LUNCH, Meal.DINNER}
    for meal, mc in counts.items():
        assert mc.meal is meal


# =========================================================================
# Adjustments (done-criterion 3)
# =========================================================================

def test_adjustment_applies_last_to_the_final_total():
    roll_today, morning, roll_next = _build_docs()
    counts = compute_meals(D, roll_today, morning, roll_next, {Meal.BREAKFAST: 2})
    bfast = counts[Meal.BREAKFAST]
    assert bfast.base_total == 2
    assert bfast.adjustment_delta == 2
    assert bfast.final_total == 4          # base + delta, applied last
    assert bfast.negative is False
    # Meals without an adjustment are untouched (delta 0).
    assert counts[Meal.LUNCH].adjustment_delta == 0
    assert counts[Meal.LUNCH].final_total == counts[Meal.LUNCH].base_total


def test_negative_final_is_flagged_and_kept_not_clamped():
    roll_today, morning, roll_next = _build_docs()
    # dinner base is 2; a -7 pushes the final to -5.
    counts = compute_meals(D, roll_today, morning, roll_next, {Meal.DINNER: -7})
    dinner = counts[Meal.DINNER]
    assert dinner.adjustment_delta == -7
    assert dinner.final_total == -5        # kept as-is, never floored to 0
    assert dinner.negative is True


def test_empty_adjustments_leaves_final_equal_to_base():
    roll_today, morning, roll_next = _build_docs()
    counts = compute_meals(D, roll_today, morning, roll_next, {})
    for mc in counts.values():
        assert mc.adjustment_delta == 0
        assert mc.final_total == mc.base_total
        assert mc.negative is False


def test_adjustment_does_not_change_the_nsf_subcount():
    # An adjustment is a coarse ± on the headcount; it is never attributed to
    # NSF vs regular, so the NSF sub-count stays a property of the derived base.
    roll_today, morning, roll_next = _build_docs()
    counts = compute_meals(D, roll_today, morning, roll_next, {Meal.LUNCH: 5})
    assert counts[Meal.LUNCH].base_nsf == 3
    assert counts[Meal.LUNCH].final_total == 9


# =========================================================================
# Purity — domain/meals.py must not import flask/services/models
# =========================================================================

def test_meals_module_stays_pure():
    source = Path("app/domain/meals.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not node.module.startswith("flask"), node.module
            if node.module.startswith("app"):
                assert node.module.startswith("app.domain"), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("app."), alias.name
                assert not alias.name.startswith("flask"), alias.name
