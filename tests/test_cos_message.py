"""P3b.1 — COS message (PARADE_FORMATS Message 1) compute + golden text.

Pure unit tests with duck-typed fakes (same style as test_morning_parade /
test_presence_engine): no app, no DB. Pairs are built by driving the real
presence `resolve()` with dated rows, so date-coverage claims — an MC spanning
D inherits, a single-day D-1 artifact does not — are proven honestly, not
asserted by fiat. The golden string pins `render_cos` to the Message 1 skeleton
byte-for-byte via "\n".join (never a triple-quoted literal — that couples the
golden to git's CRLF checkout; render_cos emits LF).
"""
import ast
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain import parade
from app.domain.presence import resolve
from app.domain.types import (
    CourseAbsenceType, DayPart, LeaveType, Rank, Service, StatusType,
)

DAY = date(2026, 7, 6)  # D, the next duty day → DDMMYY "060726"
YESTERDAY = DAY - timedelta(days=1)


# --- duck-typed fakes (feed the real resolve engine) ---------------------

def person(display_name, *, service=Service.NSF, stay_out=False, id=0):
    # `display_name` is passed "RANK Name" for brevity; the fake mirrors the real
    # Person, which since ee20005 holds the plain name with rank as a separate enum
    # column. Split them here so parade_line pairs them back into "RANK NAME".
    rank_token, _, plain = display_name.partition(" ")
    return SimpleNamespace(
        id=id, display_name=plain, rank=Rank(rank_token), service=service,
        stay_out=stay_out,
    )


def leave_row(type, start=DAY, end=DAY, day_part=DayPart.FULL):
    return SimpleNamespace(type=type, start_date=start, end_date=end, day_part=day_part)


def course_row(start=DAY, end=DAY, remarks="Sig Course"):
    # A synthesized TP-calendar course cover — since P9.5 the ONE source of
    # ON COURSE (there is no keyed course status). `remarks` is the TP event
    # title, which the ON COURSE line prints ahead of its dates.
    return SimpleNamespace(type=CourseAbsenceType.COURSE, start_date=start,
                           end_date=end, day_part=DayPart.FULL, remarks=remarks)


def status_row(type, start=DAY, end=DAY, *, in_camp, day_part=DayPart.FULL, remarks=None):
    return SimpleNamespace(
        type=type, start_date=start, end_date=end,
        in_camp=in_camp, day_part=day_part, remarks=remarks,
    )


def pair(p, **rows):
    # (person, resolution) for day D, resolved through the real engine.
    return (p, resolve(p, DAY, **rows))


# --- golden: an NSF PS as COS, the six categories exercised (criterion 1) -

# NSF PS running duty on D; the greeting takes the display STRING, not a Person
# (the COS may be typed as free text and need not be on the roster at all).
COS = parade.parade_line(person("SSG Ethan Ng"))


def _cos_roster():
    # Fed in parade order; compute preserves order within each category.
    return [
        # two flagged stay-out regulars → STAY OUT (no overriding absence)
        pair(person("CPT Oscar Ong", service=Service.REGULAR, stay_out=True, id=1)),
        pair(person("MSG Michael Tan", service=Service.REGULAR, stay_out=True, id=2)),
        # approved LL covering D → LEAVE
        pair(person("CPL Jordan Teo", id=3), leaves=[leave_row(LeaveType.LL)]),
        # approved OFF covering D → OFF/OIL
        pair(person("CFC Daniel Lim", id=4), leaves=[leave_row(LeaveType.OFF)]),
        # MC keyed earlier, range spans D → inherited via coverage → MC
        pair(person("3SG Ravi Kumar", id=5),
             statuses=[status_row(StatusType.MC, start=DAY - timedelta(days=3),
                                  end=DAY + timedelta(days=2), in_camp=False)]),
        # clean NSFs → PRESENT → omitted (this message is a request, not a parade)
        pair(person("PTE Aaron Goh", id=6)),
        pair(person("PTE Ben Chua", id=7)),
    ]


GOLDEN_COS = "\n".join([
    "Hello all, SSG ETHAN NG is the COS for 060726. Please indicate if you are on course/off/ma etc:",
    "",
    "STAY OUT (2):",
    "1. CPT OSCAR ONG",
    "2. MSG MICHAEL TAN",
    "",
    "LEAVE (1):",
    "1. CPL JORDAN TEO (060726)",
    "",
    "OFF/OIL (1):",
    "1. CFC DANIEL LIM (060726)",
    "",
    "ON COURSE (0):",
    "",
    "MC (1):",
    "1. 3SG RAVI KUMAR (030726 - 080726)",
    "",
    "OTHERS (0):",
])


def test_golden_cos_message_byte_exact():
    doc = parade.compute_cos_message(DAY, COS, _cos_roster())
    assert parade.render_cos(doc) == GOLDEN_COS


def test_golden_cos_counts_and_empty_headers():
    doc = parade.compute_cos_message(DAY, COS, _cos_roster())
    rendered = parade.render_cos(doc)
    assert "STAY OUT (2):" in rendered
    assert "MC (1):" in rendered
    # Empty categories are header-only — no numbered placeholder line.
    assert "ON COURSE (0):" in rendered
    assert "ON COURSE (0):\n1." not in rendered
    assert "OTHERS (0):" in rendered


# --- criterion 2: a covering absence overrides the stay-out flag

def test_regular_out_of_camp_status_overrides_stay_out():
    # A flagged stay-out regular would land in STAY OUT, but an out-of-camp
    # status covering D wins. (Regulars have no in-app leave since P9.3 — their
    # off/leave lives in ARCTIC FOE — so a keyed status is the only thing that
    # moves them.)
    p = person("CPT Oscar Ong", service=Service.REGULAR, stay_out=True, id=1)
    pairs = [pair(p, statuses=[status_row(StatusType.OTHER, in_camp=False)])]
    doc = parade.compute_cos_message(DAY, COS, pairs)
    assert doc.others == ("CPT OSCAR ONG (OTHER: 060726)",)
    assert doc.stay_out == ()


# --- criterion 3: single-day D-1 / in-camp artifacts never reach Message 1 -

def test_yesterday_fp_quickadd_absent_from_todays_message():
    # An FP "not joining" quick-add is a single-day in-camp OTHER on D-1; it
    # does not cover D, so the NSF resolves PRESENT and is omitted entirely.
    p = person("3SG Oliver Zhao", id=1)
    fp = status_row(StatusType.OTHER, start=YESTERDAY, end=YESTERDAY,
                    in_camp=True, remarks="BDO")
    doc = parade.compute_cos_message(DAY, COS, [pair(p, statuses=[fp])])
    rendered = parade.render_cos(doc)
    assert "OLIVER ZHAO" not in rendered
    assert doc.others == () and doc.stay_out == ()


def test_in_camp_briefing_covering_d_absent_from_message():
    # An in-camp briefing spanning D is an annotation, never absent-making, and
    # Message 1 has no OTHERS IN CAMP category — so the person appears nowhere.
    p = person("3SG Oliver Zhao", id=1)
    briefing = status_row(StatusType.OTHER, start=YESTERDAY,
                          end=DAY + timedelta(days=1), in_camp=True, remarks="Briefing")
    doc = parade.compute_cos_message(DAY, COS, [pair(p, statuses=[briefing])])
    assert "OLIVER ZHAO" not in parade.render_cos(doc)


# --- criterion 4: clean NSFs omitted; the message lists only a subset ------

def test_present_and_duty_nsfs_are_omitted():
    from app.domain.presence import PresenceState, Resolution
    pairs = [
        (person("PTE Aaron Goh", id=1), Resolution(state=PresenceState.PRESENT)),
        (person("3SG On Duty", id=2), Resolution(state=PresenceState.DUTY)),
    ]
    doc = parade.compute_cos_message(DAY, COS, pairs)
    rendered = parade.render_cos(doc)
    assert "AARON GOH" not in rendered
    assert "ON DUTY" not in rendered
    # Every category empty → header-only rhythm holds with no listed people.
    assert doc.stay_out == () == doc.leave == doc.off_oil == doc.on_course
    assert doc.mc == () == doc.others


# --- absent-row kinds route through the shared _absent_category mapping ----

@pytest.mark.parametrize(
    "row, category, suffix",
    [
        (leave_row(LeaveType.OFF), "off_oil", "(060726)"),
        (leave_row(LeaveType.OIL), "off_oil", "(060726)"),
        (leave_row(LeaveType.LL), "leave", "(060726)"),
        (leave_row(LeaveType.OL), "leave", "(060726)"),
        (status_row(StatusType.MC, in_camp=False), "mc", "(060726)"),
        (course_row(), "on_course", "(SIG COURSE: 060726)"),
        (status_row(StatusType.OTHER, in_camp=False, remarks="HL"), "others",
         "(HL: 060726)"),
    ],
)
def test_absent_kind_maps_to_cos_category(row, category, suffix):
    p = person("3SG Test Person", id=1)
    # Route the row to the right resolve() argument by its enum family.
    kwargs = {LeaveType: "leaves", StatusType: "statuses",
              CourseAbsenceType: "courses"}[type(row.type)]
    doc = parade.compute_cos_message(DAY, COS, [pair(p, **{kwargs: [row]})])
    assert getattr(doc, category) == (f"3SG TEST PERSON {suffix}",)


def test_cos_stay_out_lines_stay_bare():
    # STAY OUT comes from the person flag, not an absence row: there is no
    # backing row, so the line must carry no date range.
    p = person("CPT Oscar Ong", service=Service.REGULAR, stay_out=True, id=1)
    doc = parade.compute_cos_message(DAY, COS, [pair(p)])
    assert doc.stay_out == ("CPT OSCAR ONG",)


# --- guards -----------------------------------------------------------------

def test_double_listed_cos_doc_raises_on_validate():
    # The at-most-once guarantee: a hand-built doc with a name in two categories
    # is refused (compute can't produce this, but the invariant is enforced).
    doc = parade.CosDoc(
        day=DAY, cos_display=COS,
        stay_out=("CPT OSCAR ONG",),
        leave=("CPT OSCAR ONG",),
    )
    with pytest.raises(parade.ParadeImbalance):
        doc.validate()


# --- purity (Message 1 renderer must not import flask/services/models) -----

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
