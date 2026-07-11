import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.domain import parade
from app.domain.dates import format_ddmmyy
from app.domain.types import RANK_ORDER, Appointment, Rank


def person(id, appointment, rank, platoon, display_name):
    return SimpleNamespace(
        id=id, appointment=appointment, rank=rank, platoon=platoon, display_name=display_name
    )


# --- done-criterion 3: totality --------------------------------------------

def test_parade_rank_order_covers_every_rank():
    assert set(parade.PARADE_RANK_ORDER) == set(Rank)


def test_parade_appointment_order_covers_every_appointment():
    assert set(parade.PARADE_APPOINTMENT_ORDER) == set(Appointment)


# --- done-criterion 2: display order diverges from legal RANK_ORDER at 3WO -

def test_parade_rank_order_diverges_from_legal_rank_order_at_3wo():
    # Decision (g): parade display hoists 3WO above LTA (unit convention).
    # PARADE_RANK_ORDER: lower index displays first, so 3WO (idx) < LTA (idx).
    assert parade.PARADE_RANK_ORDER[Rank.THREE_WO] < parade.PARADE_RANK_ORDER[Rank.LTA]
    # Legal RANK_ORDER is untouched: higher value = more senior, and LTA
    # outranks 3WO there (12 > 10) — the two orderings deliberately disagree
    # so nobody "fixes" the hoist by reusing/aligning with RANK_ORDER.
    assert RANK_ORDER[Rank.LTA] > RANK_ORDER[Rank.THREE_WO]


# --- done-criterion 1: mixed-roster sort ------------------------------------

def test_parade_sort_key_orders_mixed_roster_per_decision_g():
    oc = person(1, Appointment.OC, Rank.CPT, None, "CPT Oscar Ong")
    two_ic = person(2, Appointment.TWO_IC, Rank.LTA, None, "LTA Iris Ng")
    sm = person(3, Appointment.SM, Rank.THREE_WO, None, "3WO Sam Wee")  # 3WO SM
    pc1 = person(4, Appointment.PC, Rank.LTA, 1, "LTA Pat Cheng")
    pc2 = person(5, Appointment.PC, Rank.LTA, 2, "LTA Pia Chong")
    p2ic = person(6, Appointment.P2IC, Rank.MSG, 1, "MSG Mike Pace")  # MSG P2IC
    ps = person(7, Appointment.PS, Rank.THREE_SG, 1, "3SG Percy Sim")
    det_comd = person(8, Appointment.DET_COMD, Rank.THREE_SG, 1, "3SG Derek Chan")
    # Same appointment/rank/platoon: id order must win, so pick names that
    # would reorder alphabetically if anyone alphabetized by mistake.
    opr_first = person(9, Appointment.OPR, Rank.PTE, 1, "PTE Zed Yeo")
    opr_second = person(10, Appointment.OPR, Rank.PTE, 1, "PTE Amy Poh")

    expected = [oc, two_ic, sm, pc1, pc2, p2ic, ps, det_comd, opr_first, opr_second]
    shuffled = [pc2, opr_second, sm, det_comd, oc, opr_first, p2ic, pc1, ps, two_ic]

    result = sorted(shuffled, key=parade.parade_sort_key)
    assert result == expected


# --- done-criterion 4: line format + date format ---------------------------

def test_parade_line_uppercases_display_name():
    p = person(1, Appointment.OPR, Rank.CPL, 2, "Ismail Bin Hassan")
    assert parade.parade_line(p) == "CPL ISMAIL BIN HASSAN"


def test_format_ddmmyy():
    assert format_ddmmyy(date(2026, 7, 6)) == "060726"


# --- done-criterion 5: purity ------------------------------------------------

def test_parade_module_imports_only_stdlib_and_domain():
    # P3a.6 widened parade.py to import sibling pure domain modules
    # (presence, dates) — still no flask/services/models: stdlib + app.domain.*.
    source = Path("app/domain/parade.py").read_text()
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
