"""P10.3 (was P8.4) — pure domain for drag-and-drop parade overrides.

No app, no DB: duck-typed fakes drive categorize / compute_cos_message to build
real ParadeDoc/CosDoc, then apply_overrides moves people between categories. The
existing byte-exact goldens (test_morning_parade / test_roll_call /
test_cos_message) are the regression gate for the rendered output; this file pins
the override semantics themselves — including decision D4, where CURRENT_STRENGTH
on the COS message means "remove the line", not "move it to a bucket".
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain import parade
from app.domain.presence import PresenceState, Resolution
from app.domain.types import (
    ALLOWED_OVERRIDE_TARGETS,
    Appointment,
    LeaveType,
    OverrideCategory,
    ParadeVariant,
    Rank,
    StatusType,
)

DAY = date(2026, 7, 6)

COS_DISPLAY = "SSG ETHAN NG"


# --- duck-typed fakes (carry the fields parade_sort_key + parade_line read) --

def person(display_name, *, id, appointment=Appointment.OPR, platoon=1):
    rank_token, _, plain = display_name.partition(" ")
    return SimpleNamespace(
        id=id, display_name=plain, rank=Rank(rank_token),
        appointment=appointment, platoon=platoon,
    )


def absent(row):
    return Resolution(state=PresenceState.ABSENT, row=row)


def present(in_camp_rows=()):
    return Resolution(state=PresenceState.PRESENT, in_camp_rows=tuple(in_camp_rows))


def stay_out():
    return Resolution(state=PresenceState.STAY_OUT)


def leave_row(type):
    return SimpleNamespace(type=type)


def status_row(type, remarks=None):
    return SimpleNamespace(type=type, remarks=remarks)


# --- shared docs -------------------------------------------------------------

def _morning_doc():
    pairs = [
        (person("PTE Aaron Goh", id=1), present()),
        (person("PTE Ben Chua", id=2), present()),
        (person("3SG Oliver Zhao", id=3),
         present(in_camp_rows=[status_row(StatusType.OTHER, remarks="BDO")])),
        (person("CPL Jordan Teo", id=4), absent(leave_row(LeaveType.LL))),
        (person("3SG Ravi Kumar", id=5), absent(status_row(StatusType.MC))),
    ]
    return parade.categorize(DAY, pairs, "morning")


def _roll_call_doc():
    pairs = [
        (person("PTE Aaron Goh", id=1), present()),
        (person("PTE Ben Chua", id=2), present()),
        (person("CPT Oscar Ong", id=3, appointment=Appointment.OC), stay_out()),
        (person("3SG Ravi Kumar", id=5), absent(status_row(StatusType.MC))),
    ]
    return parade.categorize(DAY, pairs, "roll_call")


def _cos_doc():
    pairs = [
        (person("CPT Oscar Ong", id=3, appointment=Appointment.OC), stay_out()),
        (person("CPL Jordan Teo", id=4), absent(leave_row(LeaveType.LL))),
        (person("3SG Ravi Kumar", id=5), absent(status_row(StatusType.MC))),
    ]
    return parade.compute_cos_message(DAY, COS_DISPLAY, pairs)


# --- move semantics ----------------------------------------------------------

def test_morning_into_others_in_camp_has_no_reason_parenthesis():
    doc = _morning_doc()
    moved = parade.apply_overrides(doc, {1: OverrideCategory.OTHERS_IN_CAMP})
    assert "PTE AARON GOH" in moved.others_in_camp
    # A dragged-in OTHERS IN CAMP line is bare — the "(REASON)" suffix is a
    # keyer annotation, never synthesised by a drag.
    assert "PTE AARON GOH (" not in "".join(moved.others_in_camp)


def test_reason_suffix_dropped_when_dragged_out_of_others_in_camp():
    doc = _morning_doc()
    # Oliver Zhao sits in OTHERS IN CAMP as "3SG OLIVER ZHAO (BDO)".
    assert "3SG OLIVER ZHAO (BDO)" in doc.others_in_camp
    moved = parade.apply_overrides(doc, {3: OverrideCategory.MC})
    assert "3SG OLIVER ZHAO" in moved.mc
    assert "(BDO)" not in "".join(moved.mc)
    # Source doc untouched — apply_overrides returns a fresh frozen copy.
    assert "3SG OLIVER ZHAO (BDO)" in doc.others_in_camp
    # The person is gone from OTHERS IN CAMP entirely in the moved copy.
    assert all("OLIVER ZHAO" not in line for line in moved.others_in_camp)


def test_roll_call_stay_out_round_trip():
    doc = _roll_call_doc()
    assert "PTE AARON GOH" in doc.current_strength
    out = parade.apply_overrides(doc, {1: OverrideCategory.STAY_OUT})
    assert "PTE AARON GOH" in out.stay_out
    assert all("AARON GOH" not in line for line in out.current_strength)
    back = parade.apply_overrides(out, {1: OverrideCategory.CURRENT_STRENGTH})
    assert "PTE AARON GOH" in back.current_strength
    assert all("AARON GOH" not in line for line in back.stay_out)


def test_cos_move_uses_people_tuples():
    doc = _cos_doc()
    assert "CPT OSCAR ONG" in doc.stay_out
    moved = parade.apply_overrides(doc, {3: OverrideCategory.LEAVE})
    assert "CPT OSCAR ONG" in moved.leave
    assert all("OSCAR ONG" not in line for line in moved.stay_out)
    # The parallel person tuple moved in lockstep with the line tuple.
    assert 3 in [p.id for p in moved.leave_people]
    assert 3 not in [p.id for p in moved.stay_out_people]


def test_cos_current_strength_target_removes_person_from_message():
    # Decision D4: Message 1 lists only people with something to report, so
    # "present" is not a bucket there — dragging onto it drops the line entirely.
    doc = _cos_doc()
    moved = parade.apply_overrides(doc, {5: OverrideCategory.CURRENT_STRENGTH})
    rendered = parade.render_cos(moved)
    assert "RAVI KUMAR" not in rendered
    assert moved.mc == () and moved.mc_people == ()
    # Nobody else moved, and no CosDoc bucket picked the person up.
    assert all(
        5 not in [p.id for p in getattr(moved, f"{name}_people")]
        for name in parade._COS_CATEGORIES
    )
    assert "CPL JORDAN TEO" in moved.leave


def test_unknown_person_id_silently_skipped():
    doc = _morning_doc()
    moved = parade.apply_overrides(doc, {999: OverrideCategory.MC})
    # A stale override (person no longer in the doc) self-heals: no error, and
    # every category matches the original.
    for key in parade._PARADE_CATEGORIES:
        assert getattr(moved, key) == getattr(doc, key)


def test_same_bucket_override_is_noop():
    doc = _morning_doc()
    # Aaron is already CURRENT STRENGTH; a drag onto his own category changes
    # nothing but still validates.
    moved = parade.apply_overrides(doc, {1: OverrideCategory.CURRENT_STRENGTH})
    assert moved.current_strength == doc.current_strength


@pytest.mark.parametrize(
    "doc_factory, variant, bad_target",
    [
        (_morning_doc, ParadeVariant.MORNING, OverrideCategory.STAY_OUT),
        (_roll_call_doc, ParadeVariant.ROLL_CALL, OverrideCategory.OTHERS_IN_CAMP),
        (_cos_doc, ParadeVariant.COS_MESSAGE, OverrideCategory.OTHERS_IN_CAMP),
    ],
)
def test_disallowed_target_raises_value_error(doc_factory, variant, bad_target):
    assert bad_target not in ALLOWED_OVERRIDE_TARGETS[variant]
    doc = doc_factory()
    a_person_id = next(
        p.id for key in parade._doc_categories(doc)
        for p in getattr(doc, key + "_people")
    )
    with pytest.raises(ValueError):
        parade.apply_overrides(doc, {a_person_id: bad_target})


def test_cos_message_allows_current_strength_as_a_target():
    # The COS counterpart of the guard above: CURRENT_STRENGTH is legal here
    # (D4) even though the document has no such block.
    assert OverrideCategory.CURRENT_STRENGTH in ALLOWED_OVERRIDE_TARGETS[
        ParadeVariant.COS_MESSAGE
    ]


def test_empty_mapping_returns_identity():
    doc = _morning_doc()
    assert parade.apply_overrides(doc, {}) is doc
    # And a golden render is unchanged through an empty-override pass.
    assert parade.render_morning(parade.apply_overrides(doc, {})) == parade.render_morning(doc)


def test_insertion_lands_at_parade_sort_position():
    # current_strength holds a command-team CPT, then two PTEs in platoons 1 & 3;
    # a moved PTE in platoon 2 must land BETWEEN them, not appended at the end.
    pairs = [
        (person("CPT Anchor One", id=10, appointment=Appointment.OC, platoon=None), present()),
        (person("PTE Plat One", id=2, platoon=1), present()),
        (person("PTE Plat Three", id=8, platoon=3), present()),
        (person("PTE Plat Two", id=5, platoon=2), absent(status_row(StatusType.MC))),
    ]
    doc = parade.categorize(DAY, pairs, "morning")
    moved = parade.apply_overrides(doc, {5: OverrideCategory.CURRENT_STRENGTH})
    assert [p.id for p in moved.current_strength_people] == [10, 2, 5, 8]
    assert moved.current_strength[2] == "PTE PLAT TWO"


def test_moved_document_still_reassembles_from_its_sections():
    # sheet_sections (P10.2) is the one line source; an overridden doc must
    # describe itself as faithfully as a raw one.
    doc = parade.apply_overrides(_morning_doc(), {1: OverrideCategory.MC})
    sections = parade.sheet_sections(doc)
    assert "\n\n".join(s.text for s in sections) == parade.render_morning(doc)
