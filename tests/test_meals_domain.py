"""Meals domain (P3b.5, reworked by owner decision (j) 2026-07-07, revised by
(bb) 2026-07-29 and (cc) 2026-07-30) + the ParadeDoc person-list extension that
makes it possible.

The compute is exactly one counter per day — the people in camp at morning(D)
— over every NSF plus the regulars who opt in (decision (bb)). Decision (cc)
removed the second counter that read roll_call(D+1); the earlier per-meal
compute with manual adjustments was removed by decision (j).

Pure unit tests with duck-typed fakes (same style as test_roll_call /
test_morning_parade): no app, no DB. The fixture docs are built by driving the
REAL presence `resolve()` and `categorize()`, so the counter <-> document
mapping is proven honestly against the engine, never asserted by fiat.
"""
import ast
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain import parade
from app.domain.meals import day_in_camp
from app.domain.presence import PresenceState, Resolution, resolve
from app.domain.types import (
    CourseAbsenceType, DayPart, LeaveType, Meal, Rank, Service, StatusType,
)

D = date(2026, 7, 6)      # the day meals are computed for
DAY = D                   # alias used by the parade-people section


# --- duck-typed fakes ----------------------------------------------------

def person(display_name, *, service=Service.NSF, stay_out=False,
           meals_opt_in=False, id):
    # `display_name` is passed "RANK Name" for brevity; the fake mirrors the real
    # Person, which since ee20005 holds the plain name with rank as a separate enum
    # column. Split them here so parade_line pairs them back into "RANK NAME".
    # resolve() reads service/stay_out; the meal sub-count and person-identity
    # dedup read service/meals_opt_in and id.
    rank_token, _, plain = display_name.partition(" ")
    return SimpleNamespace(
        id=id, display_name=plain, rank=Rank(rank_token), service=service,
        stay_out=stay_out, meals_opt_in=meals_opt_in,
    )


def leave_row(type, start=D, end=D, day_part=DayPart.FULL):
    return SimpleNamespace(type=type, start_date=start, end_date=end, day_part=day_part)


def course_row(start=D, end=D, remarks="Sig Course"):
    # A synthesized TP-calendar course cover — since P9.5 the ONE source of
    # ON COURSE (there is no keyed course status). `remarks` is the TP event
    # title, which the ON COURSE line prints ahead of its dates.
    return SimpleNamespace(type=CourseAbsenceType.COURSE, start_date=start,
                           end_date=end, day_part=DayPart.FULL, remarks=remarks)


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
        (p7, absent(course_row())),                        # → ON COURSE
        (p8, absent(status_row(StatusType.OTHER))),         # → OTHERS (out of camp)
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
# Fixture day — the meal counter by persona (decisions (j)/(bb)/(cc))
# =========================================================================
#
# Roster (each row carries the rows fed to resolve() for day D):
#   A  stay-out NSF          — books out every night
#   B  stay-in NSF           — present around the clock
#   C  MC NSF                — MC covering D-2..D+3 (covers D)
#   E  PM-off stay-in NSF    — OFF, PM day-part, single day D only
#   F  regular (stay-out)    — no opt-in, so never counted
#   G  in-camp-status NSF    — single-day OTHER in_camp (e.g. BDO), day D only
#
# The one document that feeds the counter (decision (cc)):
#   day_in_camp(D) = morning(D) PRESENT IN CAMP, counted people only

A = person("3SG Stayout Nsf", service=Service.NSF, stay_out=True, id=1)
B = person("3SG Stayin Nsf", service=Service.NSF, stay_out=False, id=2)
C = person("3SG Mc Nsf", service=Service.NSF, stay_out=False, id=3)
E = person("3SG Pmoff Nsf", service=Service.NSF, stay_out=False, id=4)
F = person("CPT Regular Guy", service=Service.REGULAR, stay_out=False, id=5)
G = person("3SG Bdo Nsf", service=Service.NSF, stay_out=False, id=6)

ROSTER = [A, B, C, E, F, G]
ROWS = {
    A.id: {},
    B.id: {},
    C.id: {"statuses": [status_row(StatusType.MC, start=D - timedelta(days=2),
                                   end=D + timedelta(days=3), in_camp=False)]},
    E.id: {"leaves": [leave_row(LeaveType.OFF, start=D, end=D, day_part=DayPart.PM)]},
    F.id: {},
    G.id: {"statuses": [status_row(StatusType.OTHER, start=D, end=D,
                                   in_camp=True, remarks="BDO")]},
}


def _pairs_for(day):
    return [(p, resolve(p, day, **ROWS[p.id])) for p in ROSTER]


def _morning_doc():
    return parade.categorize(D, _pairs_for(D), "morning")


def test_day_count_is_nsfs_present_in_camp_by_day():
    # morning(D) PRESENT IN CAMP: A (stay-out dissolves by day), B, E (PM-off
    # present at morning parade, decision i), G (in-camp status -> OTHERS IN
    # CAMP). C is on MC; F is present but an opted-out regular. Counted: A, B,
    # E, G.
    assert day_in_camp(_morning_doc()) == 4


def _count_for(*people):
    morning = parade.categorize(D, [(p, resolve(p, D)) for p in people], "morning")
    return day_in_camp(morning)


def test_regular_without_opt_in_is_not_counted():
    assert _count_for(F) == 0


def test_opted_in_regular_is_counted():
    # Decision (bb): the regulars who eat in camp tick the flag and land in the
    # indent. Presence is unchanged by the flag — a regular is stay-out by rule
    # (presence.py:155), which dissolves by day, so an opted-in regular is in
    # the day's count.
    opted_in = person("CPT Eats In", service=Service.REGULAR, stay_out=False,
                      meals_opt_in=True, id=90)
    assert _count_for(opted_in) == 1


def test_nsf_is_counted_regardless_of_the_flag():
    # NSFs are counted always; the flag is a no-op on them (it exists so a
    # keyer can never accidentally drop an NSF from an indent).
    flagged = person("3SG Flagged Nsf", service=Service.NSF, meals_opt_in=True, id=91)
    unflagged = person("3SG Plain Nsf", service=Service.NSF, meals_opt_in=False, id=92)
    assert _count_for(flagged) == _count_for(unflagged) == 1


def test_counter_is_engine_derived_not_roster_arithmetic():
    # The counter reads the categorized doc, never the roster: an MC NSF is on
    # the roster all week but appears in no number.
    total_nsfs = sum(1 for p in ROSTER if p.service is Service.NSF)
    assert day_in_camp(_morning_doc()) < total_nsfs


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
