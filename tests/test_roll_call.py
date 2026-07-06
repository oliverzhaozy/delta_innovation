"""P3b.2 — roll call state (PARADE_FORMATS Message 2) compute + golden text.

Pure unit tests with duck-typed fakes (same style as test_cos_message /
test_morning_parade): no app, no DB. Pairs are built by driving the REAL
presence `resolve()` with dated rows, so the day-part rule (AM-off absent,
PM-off present — decisions (c)/(i)) and coverage claims are proven honestly by
the engine, not asserted by fiat. The golden string pins `render_roll_call` to
the Message 2 skeleton byte-for-byte via "\n".join (never a triple-quoted
literal — that would couple the golden to git's CRLF checkout; the renderer
emits LF). "——" is two U+2014 em-dashes, per PARADE_FORMATS.md.
"""
import ast
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain import parade
from app.domain.presence import PresenceState, Resolution, resolve
from app.domain.types import DayPart, DirectAbsenceType, LeaveType, Service, StatusType

DAY = date(2026, 7, 6)  # D, the next duty day → DDMMYY "060726"
YESTERDAY = DAY - timedelta(days=1)


# --- duck-typed fakes (feed the real resolve engine) ---------------------

def person(display_name, *, service=Service.NSF, stay_out=False, is_active=True, id=0):
    # resolve() reads service/stay_out/is_active; parade_line reads display_name.
    return SimpleNamespace(
        id=id, display_name=display_name, service=service,
        stay_out=stay_out, is_active=is_active,
    )


def leave_row(type, start=DAY, end=DAY, day_part=DayPart.FULL):
    return SimpleNamespace(type=type, start_date=start, end_date=end, day_part=day_part)


def direct_row(type, start=DAY, end=DAY, day_part=DayPart.FULL):
    return SimpleNamespace(type=type, start_date=start, end_date=end, day_part=day_part)


def status_row(type, start=DAY, end=DAY, *, in_camp, day_part=DayPart.FULL, remarks=None):
    return SimpleNamespace(
        type=type, start_date=start, end_date=end,
        in_camp=in_camp, day_part=day_part, remarks=remarks,
    )


def pair(p, **rows):
    # (person, resolution) for day D, resolved through the real engine.
    return (p, resolve(p, DAY, **rows))


# --- golden: a mixed 7-person roll call (done-criterion 1) ---------------

def _roll_call_roster():
    # Fed in parade order; categorize preserves order within each category.
    return [
        # a regular and a stay-out NSF → STAY OUT (a night category on roll call)
        pair(person("CPT Oscar Ong", service=Service.REGULAR, id=1)),
        pair(person("3SG Ryan Tan", stay_out=True, id=2)),
        # approved LL covering D → LEAVE
        pair(person("CPL Jordan Teo", id=3), leaves=[leave_row(LeaveType.LL)]),
        # AM OFF → absent for the day (decision (i)) → OFF/OIL
        pair(person("CFC Daniel Lim", id=4),
             leaves=[leave_row(LeaveType.OFF, day_part=DayPart.AM)]),
        # MC keyed earlier, range spans D → inherited via coverage → MC
        pair(person("3SG Ravi Kumar", id=5),
             statuses=[status_row(StatusType.MC, start=DAY - timedelta(days=3),
                                  end=DAY + timedelta(days=2), in_camp=False)]),
        # PM OFF → present at night (expected back — decision (c)) → CURRENT STRENGTH
        pair(person("PTE Aaron Goh", id=6),
             leaves=[leave_row(LeaveType.OFF, day_part=DayPart.PM)]),
        # clean NSF → PRESENT → CURRENT STRENGTH
        pair(person("PTE Ben Chua", id=7)),
    ]


# Byte-level authority: docs/PARADE_FORMATS.md Message 2 skeleton. Title,
# strength lines, "——" separators, PRESENT/NOT PRESENT blocks, OTHERS IN CAMP
# always header-only with literal 0, category order STAY OUT/LEAVE/OFF-OIL/ON
# COURSE/MC/OTHERS. Exhibits both day parts: AM-off in OFF/OIL, PM-off present.
GOLDEN_ROLL_CALL = "\n".join([
    "DELTA ROLL CALL STATE:",
    "060726",
    "",
    "TOTAL STRENGTH: 7",
    "",
    "CURRENT STRENGTH: 2",
    "",
    "ABSENT STRENGTH: 5",
    "",
    "——",
    "",
    "PRESENT IN CAMP (2):",
    "",
    "CURRENT STRENGTH (2):",
    "1. PTE AARON GOH",
    "2. PTE BEN CHUA",
    "",
    "OTHERS IN CAMP (0):",
    "",
    "——",
    "",
    "NOT PRESENT IN CAMP (5):",
    "",
    "STAY OUT (2):",
    "1. CPT OSCAR ONG",
    "2. 3SG RYAN TAN",
    "",
    "LEAVE (1):",
    "1. CPL JORDAN TEO",
    "",
    "OFF/OIL (1):",
    "1. CFC DANIEL LIM",
    "",
    "ON COURSE (0):",
    "",
    "MC (1):",
    "1. 3SG RAVI KUMAR",
    "",
    "OTHERS (0):",
])


def test_golden_roll_call_byte_exact():
    doc = parade.categorize(DAY, _roll_call_roster(), "roll_call")
    assert parade.render_roll_call(doc) == GOLDEN_ROLL_CALL


def test_golden_roll_call_counts_derive_from_lists():
    # Header counts must equal len() of the rendered lists (cannot disagree).
    doc = parade.categorize(DAY, _roll_call_roster(), "roll_call")
    rendered = parade.render_roll_call(doc)
    assert "TOTAL STRENGTH: 7" in rendered
    assert "CURRENT STRENGTH: 2" in rendered
    assert "ABSENT STRENGTH: 5" in rendered
    assert "PRESENT IN CAMP (2):" in rendered
    assert "NOT PRESENT IN CAMP (5):" in rendered
    # OTHERS IN CAMP is always header-only with a literal 0 on roll call.
    assert "OTHERS IN CAMP (0):" in rendered
    assert "OTHERS IN CAMP (0):\n1." not in rendered
    # Empty NOT-PRESENT categories are header-only too.
    assert "ON COURSE (0):" in rendered
    assert "ON COURSE (0):\n1." not in rendered
    assert "OTHERS (0):" in rendered


# --- criterion 2: absence beats stay-out; person appears once, under MC ----

def test_stay_out_person_on_mc_appears_once_under_mc():
    # A stay-out NSF with an MC covering D: the absence overrides stay-out, so
    # the person appears exactly once and only under MC — the done criterion.
    p = person("3SG Ravi Kumar", stay_out=True, id=1)
    mc = status_row(StatusType.MC, start=YESTERDAY, end=DAY + timedelta(days=1),
                    in_camp=False)
    doc = parade.categorize(DAY, [pair(p, statuses=[mc])], "roll_call")
    assert doc.mc == ("3SG RAVI KUMAR",)
    assert doc.stay_out == ()
    rendered = parade.render_roll_call(doc)
    assert rendered.count("RAVI KUMAR") == 1


# --- criterion 3: in-camp briefing — roll call keeps present, morning promotes

def test_in_camp_briefing_roll_call_vs_morning_contrast():
    # In-camp promotion is morning-only: a briefing covering D leaves the person
    # in CURRENT STRENGTH at roll call, but the SAME data promotes them to
    # OTHERS IN CAMP on the morning variant.
    p = person("3SG Oliver Zhao", id=1)
    briefing = status_row(StatusType.BRIEFING, start=YESTERDAY,
                          end=DAY + timedelta(days=1), in_camp=True)
    pr = pair(p, statuses=[briefing])

    roll = parade.categorize(DAY, [pr], "roll_call")
    assert roll.current_strength == ("3SG OLIVER ZHAO",)
    assert roll.others_in_camp == ()
    # No OTHERS IN CAMP promotion here; the header still shows the literal 0.
    assert "OTHERS IN CAMP (0):" in parade.render_roll_call(roll)

    morning = parade.categorize(DAY, [pr], "morning")
    assert morning.others_in_camp == ("3SG OLIVER ZHAO (BRIEFING)",)
    assert morning.current_strength == ()


# --- criterion 4: invariant violations raise (mirrors the morning pattern) --

def test_corrupted_roll_call_double_count_raises_on_render():
    # A person double-counted across CURRENT STRENGTH and STAY OUT: total says 1
    # but two lines are present — the app refuses to render it.
    doc = parade.ParadeDoc(
        day=DAY, variant="roll_call", total=1,
        current_strength=("3SG OLIVER ZHAO",),
        stay_out=("3SG OLIVER ZHAO",),
    )
    with pytest.raises(parade.ParadeImbalance):
        parade.render_roll_call(doc)


def test_corrupted_roll_call_drifted_total_raises():
    doc = parade.ParadeDoc(
        day=DAY, variant="roll_call", total=5,  # drifted: only two listed
        current_strength=("CPT OSCAR ONG", "PTE BEN CHUA"),
    )
    with pytest.raises(parade.ParadeImbalance):
        parade.render_roll_call(doc)


def test_roll_call_with_others_in_camp_raises():
    # Roll call has no OTHERS IN CAMP category (in-camp promotion is morning-only),
    # so a doc that populates it is refused — the symmetric guard to morning's
    # "no STAY OUT category" rule, keeping the literal "(0)" header honest.
    doc = parade.ParadeDoc(
        day=DAY, variant="roll_call", total=1,
        others_in_camp=("3SG OLIVER ZHAO (BDO)",),
    )
    with pytest.raises(parade.ParadeImbalance):
        parade.render_roll_call(doc)


def test_render_roll_call_rejects_wrong_variant():
    pairs = [(person("PTE Aaron Goh", id=1), Resolution(state=PresenceState.PRESENT))]
    doc = parade.categorize(DAY, pairs, "morning")
    with pytest.raises(ValueError):
        parade.render_roll_call(doc)


def test_valid_roll_call_doc_validates_cleanly():
    doc = parade.categorize(DAY, _roll_call_roster(), "roll_call")
    assert doc.validate() is doc  # no raise; fluent


# --- day-part semantics come free from the engine (decisions (c)/(i)) ------

def test_am_off_is_absent_pm_off_is_present():
    am = person("CFC Daniel Lim", id=1)
    pm = person("PTE Aaron Goh", id=2)
    pairs = [
        pair(am, leaves=[leave_row(LeaveType.OFF, day_part=DayPart.AM)]),
        pair(pm, leaves=[leave_row(LeaveType.OFF, day_part=DayPart.PM)]),
    ]
    doc = parade.categorize(DAY, pairs, "roll_call")
    assert doc.off_oil == ("CFC DANIEL LIM",)      # AM-off → absent
    assert doc.current_strength == ("PTE AARON GOH",)  # PM-off → present


# --- absent-row kinds route through the shared _absent_category mapping ----

@pytest.mark.parametrize(
    "row, category",
    [
        (leave_row(LeaveType.OFF), "off_oil"),
        (leave_row(LeaveType.OIL), "off_oil"),
        (leave_row(LeaveType.LL), "leave"),
        (leave_row(LeaveType.OL), "leave"),
        (direct_row(DirectAbsenceType.LEAVE), "leave"),
        (direct_row(DirectAbsenceType.OTHER), "others"),
        (status_row(StatusType.MC, in_camp=False), "mc"),
        (status_row(StatusType.COURSE, in_camp=False), "on_course"),
        (status_row(StatusType.BRIEFING, in_camp=False), "others"),
        (status_row(StatusType.SITE_TESTING, in_camp=False), "others"),
        (status_row(StatusType.OTHER, in_camp=False), "others"),
    ],
)
def test_absent_kind_maps_to_roll_call_category(row, category):
    p = person("3SG Test Person", id=1)
    kwargs = {LeaveType: "leaves", DirectAbsenceType: "direct_absences",
              StatusType: "statuses"}[type(row.type)]
    doc = parade.categorize(DAY, [pair(p, **{kwargs: [row]})], "roll_call")
    assert getattr(doc, category) == ("3SG TEST PERSON",)


# --- purity (Message 2 renderer must not import flask/services/models) ------

def test_parade_module_stays_pure():
    source = Path("app/domain/parade.py").read_text(encoding="utf-8")
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
