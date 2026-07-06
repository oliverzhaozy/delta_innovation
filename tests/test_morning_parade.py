"""P3a.6 — morning parade compute + the golden-text convention.

Pure unit tests with duck-typed fakes (same style as test_presence_engine):
no app, no DB. The two golden strings are the phase's actual product — they
pin `render_morning` to the Message 3 skeleton in docs/PARADE_FORMATS.md
byte-for-byte, so any drift in spacing, counts, or category order fails here.
"""
import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain import parade
from app.domain.presence import PresenceState, Resolution
from app.domain.types import DirectAbsenceType, LeaveType, StatusType

DAY = date(2026, 7, 6)  # → DDMMYY "060726"


# --- duck-typed fakes ----------------------------------------------------

def person(display_name, id=0):
    # parade_line reads display_name only; id rides along for realism.
    return SimpleNamespace(id=id, display_name=display_name)


def leave_row(type):
    return SimpleNamespace(type=type)


def direct_row(type):
    return SimpleNamespace(type=type)


def status_row(type, remarks=None):
    return SimpleNamespace(type=type, remarks=remarks)


def absent(row):
    return Resolution(state=PresenceState.ABSENT, row=row)


def present(in_camp_rows=()):
    return Resolution(state=PresenceState.PRESENT, in_camp_rows=tuple(in_camp_rows))


def stay_out(in_camp_rows=()):
    return Resolution(state=PresenceState.STAY_OUT, in_camp_rows=tuple(in_camp_rows))


# --- golden 1: a mixed 7-person roster (done-criterion 1) ----------------

def _mixed_roster():
    # Fed in parade order; categorize preserves order within each category.
    return [
        (person("CPT Oscar Ong", 1), stay_out()),                         # regular stay-out → CURRENT
        (person("MSG Michael Tan", 2), present()),                         # present → CURRENT
        (person("CPL Jordan Teo", 3), absent(leave_row(LeaveType.LL))),    # LL → LEAVE
        (person("CFC Daniel Lim", 4), absent(leave_row(LeaveType.OFF))),   # OFF → OFF/OIL
        (person("3SG Ravi Kumar", 5), absent(status_row(StatusType.MC))),  # MC → MC
        (person("3SG Oliver Zhao", 6),                                     # in-camp OTHER "BDO" → OTHERS IN CAMP
         present(in_camp_rows=[status_row(StatusType.OTHER, remarks="BDO")])),
        (person("PTE Aaron Goh", 7), present()),                           # present → CURRENT
    ]


# Built with "\n".join (not a triple-quoted literal) so the golden's line
# endings are ALWAYS LF regardless of git's autocrlf checkout of this file —
# render_morning emits LF, and a byte-exact test must not hinge on how the
# source was checked out. "——" is two U+2014 em-dashes (PARADE_FORMATS.md).
GOLDEN_MIXED = "\n".join([
    "DELTA MORNING PARADE STATE:",
    "060726",
    "",
    "TOTAL STRENGTH: 7",
    "",
    "CURRENT STRENGTH: 3",
    "",
    "ABSENT STRENGTH: 3",
    "",
    "——",
    "",
    "PRESENT IN CAMP (4):",
    "",
    "CURRENT STRENGTH (3):",
    "1. CPT OSCAR ONG",
    "2. MSG MICHAEL TAN",
    "3. PTE AARON GOH",
    "",
    "OTHERS IN CAMP (1):",
    "1. 3SG OLIVER ZHAO (BDO)",
    "",
    "——",
    "",
    "NOT PRESENT IN CAMP (3):",
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


def test_golden_mixed_roster_byte_exact():
    doc = parade.categorize(DAY, _mixed_roster(), "morning")
    assert parade.render_morning(doc) == GOLDEN_MIXED


def test_golden_mixed_counts_derive_from_lists():
    # Header counts must equal len() of the rendered lists (cannot disagree).
    doc = parade.categorize(DAY, _mixed_roster(), "morning")
    rendered = parade.render_morning(doc)
    assert "TOTAL STRENGTH: 7" in rendered
    assert "PRESENT IN CAMP (4):" in rendered
    assert "NOT PRESENT IN CAMP (3):" in rendered
    assert "ABSENT STRENGTH: 3" in rendered


# --- golden 2: several empty categories (done-criterion 2) ---------------

GOLDEN_EMPTY = "\n".join([
    "DELTA MORNING PARADE STATE:",
    "060726",
    "",
    "TOTAL STRENGTH: 2",
    "",
    "CURRENT STRENGTH: 2",
    "",
    "ABSENT STRENGTH: 0",
    "",
    "——",
    "",
    "PRESENT IN CAMP (2):",
    "",
    "CURRENT STRENGTH (2):",
    "1. CPT OSCAR ONG",
    "2. PTE AARON GOH",
    "",
    "OTHERS IN CAMP (0):",
    "",
    "——",
    "",
    "NOT PRESENT IN CAMP (0):",
    "",
    "LEAVE (0):",
    "",
    "OFF/OIL (0):",
    "",
    "ON COURSE (0):",
    "",
    "MC (0):",
    "",
    "OTHERS (0):",
])


def test_golden_empty_categories_header_only():
    pairs = [
        (person("CPT Oscar Ong", 1), stay_out()),
        (person("PTE Aaron Goh", 2), present()),
    ]
    doc = parade.categorize(DAY, pairs, "morning")
    assert parade.render_morning(doc) == GOLDEN_EMPTY


# --- done-criterion 3: each ABSENT row kind lands in its category --------

@pytest.mark.parametrize(
    "row, category, header",
    [
        (leave_row(LeaveType.OFF), "off_oil", "OFF/OIL"),
        (leave_row(LeaveType.OIL), "off_oil", "OFF/OIL"),
        (leave_row(LeaveType.LL), "leave", "LEAVE"),
        (leave_row(LeaveType.OL), "leave", "LEAVE"),
        (direct_row(DirectAbsenceType.LEAVE), "leave", "LEAVE"),
        (direct_row(DirectAbsenceType.OTHER), "others", "OTHERS"),
        (status_row(StatusType.MC), "mc", "MC"),
        (status_row(StatusType.COURSE), "on_course", "ON COURSE"),
        (status_row(StatusType.BRIEFING), "others", "OTHERS"),      # out-of-camp briefing
        (status_row(StatusType.SITE_TESTING), "others", "OTHERS"),
        (status_row(StatusType.OTHER), "others", "OTHERS"),
    ],
)
def test_absent_row_kind_maps_to_category(row, category, header):
    pairs = [(person("3SG Test Person", 1), absent(row))]
    doc = parade.categorize(DAY, pairs, "morning")
    assert getattr(doc, category) == ("3SG TEST PERSON",)
    # And it renders under the right header, nowhere else.
    rendered = parade.render_morning(doc)
    assert f"{header} (1):\n1. 3SG TEST PERSON" in rendered


def test_others_in_camp_reason_falls_back_to_type_label_when_no_remarks():
    # First in-camp row with no remarks → uppercased type label, not blank.
    pairs = [(person("3SG Test Person", 1),
              present(in_camp_rows=[status_row(StatusType.BRIEFING)]))]
    doc = parade.categorize(DAY, pairs, "morning")
    assert doc.others_in_camp == ("3SG TEST PERSON (BRIEFING)",)


def test_stay_out_regular_with_in_camp_row_promotes_to_others_in_camp():
    # STAY_OUT dissolves into CURRENT on morning, but an in-camp row still
    # promotes the person to OTHERS IN CAMP with the reason.
    pairs = [(person("3SG Oliver Zhao", 1),
              stay_out(in_camp_rows=[status_row(StatusType.OTHER, remarks="BDO")]))]
    doc = parade.categorize(DAY, pairs, "morning")
    assert doc.others_in_camp == ("3SG OLIVER ZHAO (BDO)",)
    assert doc.current_strength == ()


def test_duty_state_lands_in_current_strength():
    pairs = [(person("3SG On Duty", 1), Resolution(state=PresenceState.DUTY))]
    doc = parade.categorize(DAY, pairs, "morning")
    assert doc.current_strength == ("3SG ON DUTY",)


# --- done-criterion 4: roll_call STAY OUT (mapping only) ------------------

def test_roll_call_stay_out_lands_in_stay_out_category():
    pairs = [
        (person("CPT Oscar Ong", 1), stay_out()),
        (person("PTE Aaron Goh", 2), present()),
    ]
    doc = parade.categorize(DAY, pairs, "roll_call")
    assert doc.stay_out == ("CPT OSCAR ONG",)
    assert doc.current_strength == ("PTE AARON GOH",)


def test_roll_call_does_not_promote_in_camp_rows():
    # OTHERS IN CAMP is morning-only; roll call keeps in-camp people in place.
    pairs = [(person("3SG Oliver Zhao", 1),
              present(in_camp_rows=[status_row(StatusType.OTHER, remarks="BDO")]))]
    doc = parade.categorize(DAY, pairs, "roll_call")
    assert doc.others_in_camp == ()
    assert doc.current_strength == ("3SG OLIVER ZHAO",)


def test_morning_variant_has_no_stay_out_category():
    pairs = [(person("CPT Oscar Ong", 1), stay_out())]
    doc = parade.categorize(DAY, pairs, "morning")
    assert doc.stay_out == ()
    assert doc.current_strength == ("CPT OSCAR ONG",)


# --- done-criterion 5: ParadeImbalance ------------------------------------

def test_deactivated_resolution_raises():
    pairs = [(person("PTE Ghost", 1), Resolution(state=PresenceState.DEACTIVATED))]
    with pytest.raises(parade.ParadeImbalance):
        parade.categorize(DAY, pairs, "morning")


def test_corrupted_doc_double_count_raises_on_render():
    # A person double-counted across two categories: total says 1 but two
    # lines are present — the app refuses to render it.
    doc = parade.ParadeDoc(
        day=DAY,
        variant="morning",
        total=1,
        current_strength=("3SG OLIVER ZHAO",),
        others_in_camp=(),
        leave=("3SG OLIVER ZHAO",),
        off_oil=(),
        on_course=(),
        mc=(),
        others=(),
    )
    with pytest.raises(parade.ParadeImbalance):
        parade.render_morning(doc)


def test_corrupted_doc_drifted_total_raises():
    doc = parade.ParadeDoc(
        day=DAY,
        variant="morning",
        total=5,  # drifted: only two people are actually listed
        current_strength=("CPT OSCAR ONG", "PTE AARON GOH"),
        others_in_camp=(),
        leave=(),
        off_oil=(),
        on_course=(),
        mc=(),
        others=(),
    )
    with pytest.raises(parade.ParadeImbalance):
        parade.render_morning(doc)


def test_valid_doc_validates_cleanly():
    doc = parade.categorize(DAY, _mixed_roster(), "morning")
    assert doc.validate() is doc  # no raise; fluent


# --- done-criterion 6: purity ---------------------------------------------

def test_parade_module_stays_pure():
    # Pure = stdlib + sibling app.domain.* only; never flask/services/models.
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
