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


# --- golden: an NSF PS as COS, the six categories exercised (criterion 1) -

COS = person("SSG Ethan Ng")  # NSF PS running duty on D; greeting subject only.


def _cos_roster():
    # Fed in parade order; compute preserves order within each category.
    return [
        # two regulars → STAY OUT by engine default (no overriding absence)
        pair(person("CPT Oscar Ong", service=Service.REGULAR, id=1)),
        pair(person("MSG Michael Tan", service=Service.REGULAR, id=2)),
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


# --- criterion 2: a covering direct absence overrides the regular default -

def test_regular_direct_leave_overrides_stay_out():
    # A regular defaults to STAY OUT, but a direct LEAVE covering D wins.
    p = person("CPT Oscar Ong", service=Service.REGULAR, id=1)
    pairs = [pair(p, direct_absences=[direct_row(DirectAbsenceType.LEAVE)])]
    doc = parade.compute_cos_message(DAY, COS, pairs)
    assert doc.leave == ("CPT OSCAR ONG",)
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
    briefing = status_row(StatusType.BRIEFING, start=YESTERDAY,
                          end=DAY + timedelta(days=1), in_camp=True)
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
def test_absent_kind_maps_to_cos_category(row, category):
    p = person("3SG Test Person", id=1)
    # Route the row to the right resolve() argument by its enum family.
    kwargs = {LeaveType: "leaves", DirectAbsenceType: "direct_absences",
              StatusType: "statuses"}[type(row.type)]
    doc = parade.compute_cos_message(DAY, COS, [pair(p, **{kwargs: [row]})])
    assert getattr(doc, category) == ("3SG TEST PERSON",)


# --- guards -----------------------------------------------------------------

def test_deactivated_person_raises():
    from app.domain.presence import PresenceState, Resolution
    pairs = [(person("PTE Ghost", is_active=False, id=1),
              Resolution(state=PresenceState.DEACTIVATED))]
    with pytest.raises(parade.ParadeImbalance):
        parade.compute_cos_message(DAY, COS, pairs)


def test_double_listed_cos_doc_raises_on_validate():
    # The at-most-once guarantee: a hand-built doc with a name in two categories
    # is refused (compute can't produce this, but the invariant is enforced).
    doc = parade.CosDoc(
        day=DAY, cos_person=COS,
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
