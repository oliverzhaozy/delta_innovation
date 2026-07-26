"""P10.2 — `sheet_sections`: the one structured line source behind both
renderings of a parade document.

The keyer's drag sheet and the copyable WhatsApp text are the same artifact
shown twice, which is exactly the failure class where two renderers drift. The
structural fix is that the renderers ARE a join over `sheet_sections`; these
tests pin that reassembly (`"\\n\\n".join(section.text) == render_*(doc)`) on
all three variants, plus the shape guarantees the drag UI relies on: droppable
sections carry a category key and one entry per person, inert chrome carries
none, and the "N. " numbering exists in exactly one place.

Pure unit tests with duck-typed fakes (same style as test_morning_parade.py):
no app, no DB.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain import parade
from app.domain.presence import PresenceState, Resolution
from app.domain.types import CourseAbsenceType, LeaveType, Rank, StatusType

DAY = date(2026, 7, 6)  # → DDMMYY "060726"

COS_DISPLAY = "SSG ETHAN NG"


# --- duck-typed fakes ----------------------------------------------------

def person(display_name, id):
    rank_token, _, plain = display_name.partition(" ")
    return SimpleNamespace(id=id, display_name=plain, rank=Rank(rank_token))


def absent(type_):
    return Resolution(state=PresenceState.ABSENT, row=SimpleNamespace(type=type_))


def present(remarks=None):
    in_camp_rows = ()
    if remarks is not None:
        in_camp_rows = (SimpleNamespace(type=StatusType.OTHER, remarks=remarks),)
    return Resolution(state=PresenceState.PRESENT, in_camp_rows=in_camp_rows)


def stay_out():
    return Resolution(state=PresenceState.STAY_OUT)


def _roster():
    # One person in every category the three variants can print, fed in parade
    # order (compute preserves order within a category).
    return [
        (person("CPT Oscar Ong", 1), stay_out()),
        (person("MSG Michael Tan", 2), present()),
        (person("CPL Jordan Teo", 3), absent(LeaveType.LL)),
        (person("CFC Daniel Lim", 4), absent(LeaveType.OFF)),
        (person("3SG Ravi Kumar", 5), absent(StatusType.MC)),
        (person("3SG Kai Wong", 6), absent(CourseAbsenceType.COURSE)),
        (person("3SG Oliver Zhao", 7), present(remarks="BDO")),
        (person("PTE Aaron Goh", 8), absent(StatusType.OTHER)),
    ]


def _doc_and_renderer(kind, pairs):
    """(doc, renderer) for one of the three document kinds over `pairs`."""
    if kind == "cos":
        return parade.compute_cos_message(DAY, COS_DISPLAY, pairs), parade.render_cos
    renderer = parade.render_morning if kind == "morning" else parade.render_roll_call
    return parade.categorize(DAY, pairs, kind), renderer


def _docs():
    return tuple(_doc_and_renderer(kind, _roster())[0]
                 for kind in ("morning", "roll_call", "cos"))


def _keys(doc):
    return [s.key for s in parade.sheet_sections(doc) if s.key is not None]


# --- the reassembly invariant (the whole point of the refactor) -----------

@pytest.mark.parametrize("kind", ["morning", "roll_call", "cos"])
def test_sections_reassemble_into_the_rendered_document(kind):
    doc, render = _doc_and_renderer(kind, _roster())
    sections = parade.sheet_sections(doc)
    assert "\n\n".join(section.text for section in sections) == render(doc)


@pytest.mark.parametrize("kind", ["morning", "roll_call", "cos"])
def test_empty_document_sections_still_reassemble(kind):
    # Header-only categories are the boundary case: every section is present,
    # each contributing its bare "TITLE (0):" line and no entries.
    doc, render = _doc_and_renderer(kind, [])
    sections = parade.sheet_sections(doc)
    assert "\n\n".join(section.text for section in sections) == render(doc)
    assert all(section.entries == () for section in sections)


# --- section shape the drag UI reads -------------------------------------

def test_droppable_sections_are_the_variants_printed_categories():
    morning, roll_call, cos = _docs()
    assert _keys(morning) == [
        "current_strength", "others_in_camp", "leave", "off_oil",
        "on_course", "mc", "others",
    ]
    # Roll call's OTHERS IN CAMP is a literal "(0):" line, never a bucket.
    assert _keys(roll_call) == [
        "current_strength", "stay_out", "leave", "off_oil", "on_course", "mc", "others",
    ]
    assert _keys(cos) == ["stay_out", "leave", "off_oil", "on_course", "mc", "others"]


def test_droppable_entries_track_the_people_tuples():
    for doc in _docs():
        for section in parade.sheet_sections(doc):
            if section.key is None:
                continue
            people = getattr(doc, f"{section.key}_people")
            assert [e.person_id for e in section.entries] == [p.id for p in people]
            assert section.title == parade.CATEGORY_TITLES[section.key]


def test_entry_text_is_the_numbered_line_and_rebuilds_the_block():
    doc = parade.categorize(DAY, _roster(), "morning")
    section = next(s for s in parade.sheet_sections(doc) if s.key == "current_strength")
    assert section.entries[0].text == "1. CPT OSCAR ONG"
    assert [e.text for e in section.entries] == [
        f"{n}. {line}" for n, line in enumerate(doc.current_strength, 1)
    ]
    # Header + entries reassemble the section's own text exactly — the drag rows
    # and the copied block are the same strings, not two formatters.
    header = f"{section.title} ({len(section.entries)}):"
    assert "\n".join([header, *(e.text for e in section.entries)]) == section.text


def test_plain_sections_carry_no_key_title_or_entries():
    doc = parade.categorize(DAY, _roster(), "roll_call")
    plain = [s for s in parade.sheet_sections(doc) if s.key is None]
    assert plain, "the roll call skeleton has chrome sections"
    assert all(s.title is None and s.entries == () for s in plain)
    assert "OTHERS IN CAMP (0):" in [s.text for s in plain]


def test_line_only_doc_entries_carry_no_person_id():
    # A hand-built doc with no `*_people` tuples still describes itself; those
    # entries simply have nothing to drag.
    doc = parade.CosDoc(day=DAY, cos_display=COS_DISPLAY, mc=("3SG RAVI KUMAR",))
    section = next(s for s in parade.sheet_sections(doc) if s.key == "mc")
    assert section.entries == (parade.SheetEntry(person_id=None, text="1. 3SG RAVI KUMAR"),)


# --- guards ---------------------------------------------------------------

def test_sheet_sections_validates_before_describing():
    doc = parade.CosDoc(
        day=DAY, cos_display=COS_DISPLAY,
        stay_out=("CPT OSCAR ONG",), leave=("CPT OSCAR ONG",),
    )
    with pytest.raises(parade.ParadeImbalance):
        parade.sheet_sections(doc)


def test_sheet_sections_rejects_an_unknown_variant():
    doc = parade.ParadeDoc(day=DAY, variant="evening", total=0)
    with pytest.raises(ValueError):
        parade.sheet_sections(doc)
