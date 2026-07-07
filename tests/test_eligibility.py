"""P4.2 — domain/eligibility.py: who can be PICKED (assignment eligibility).

A different concept from policy.py's app access — the plan's two permission
layers. Frozen public API (addendum B4): eligible_cos, eligible_cdos, pool,
TU_SLOT_APPOINTMENTS, available. Eligibility is law over the LEGAL RANK_ORDER;
parade display order (PARADE_RANK_ORDER, 3WO hoisted) must never leak in here.
"""
import ast
from datetime import date, datetime, timedelta
from itertools import product
from pathlib import Path
from types import SimpleNamespace

from app.domain.eligibility import (
    TU_SLOT_APPOINTMENTS,
    available,
    eligible_cdos,
    eligible_cos,
    pool,
)
from app.domain.types import Appointment, DayPart, Duty, Rank

DAY = date(2026, 8, 5)  # a Wednesday


def person(rank, appointment, *, is_active=True, id=1):
    return SimpleNamespace(id=id, rank=rank, appointment=appointment, is_active=is_active)


def absence(start=DAY, end=DAY, day_part=DayPart.FULL):
    return SimpleNamespace(start_date=start, end_date=end, day_part=day_part)


def event(start_dt, end_dt):
    return SimpleNamespace(start_dt=start_dt, end_dt=end_dt)


# --- the two duty rules, exactly as written ----------------------------------

def test_cos_rule_rank_at_most_2sg_and_det_comd_or_opr():
    assert eligible_cos(person(Rank.TWO_SG, Appointment.DET_COMD))
    assert eligible_cos(person(Rank.THREE_SG, Appointment.DET_COMD))
    assert eligible_cos(person(Rank.CPL, Appointment.OPR))
    assert not eligible_cos(person(Rank.ONE_SG, Appointment.DET_COMD))  # 1SG > 2SG
    assert not eligible_cos(person(Rank.TWO_SG, Appointment.PS))        # wrong appointment


def test_cdos_rule_rank_at_least_2sg_and_pc_p2ic_ps():
    assert eligible_cdos(person(Rank.TWO_SG, Appointment.PS))
    assert eligible_cdos(person(Rank.MSG, Appointment.P2IC))
    assert eligible_cdos(person(Rank.LTA, Appointment.PC))
    assert not eligible_cdos(person(Rank.THREE_SG, Appointment.PS))     # 3SG < 2SG
    assert not eligible_cdos(person(Rank.TWO_SG, Appointment.DET_COMD)) # wrong appointment


def test_the_plans_own_trap_a_3sg_ps_satisfies_neither_rule():
    p = person(Rank.THREE_SG, Appointment.PS)
    assert not eligible_cos(p)   # PS is not Det Comd/Opr
    assert not eligible_cdos(p)  # 3SG is below 2SG
    # The rule, not the app, is the problem — the roster page shows the pools
    # so exactly this person's absence from both is visible on day one.


def test_nobody_is_dual_eligible_across_the_whole_rank_x_appointment_space():
    # 2SG legally sits in both rank ranges; the DISJOINT appointment sets are
    # what make dual-eligibility impossible. Exhaustive: 13 ranks x 8 appts.
    for rank, appt in product(Rank, Appointment):
        p = person(rank, appt)
        assert not (eligible_cos(p) and eligible_cdos(p)), (rank, appt)


# --- pools --------------------------------------------------------------------

def test_pool_filters_by_rule_and_activity():
    a = person(Rank.THREE_SG, Appointment.DET_COMD, id=1)
    b = person(Rank.CPL, Appointment.OPR, id=2)
    c = person(Rank.CPL, Appointment.OPR, is_active=False, id=3)   # deactivated
    d = person(Rank.TWO_SG, Appointment.PS, id=4)                  # CDOS material
    assert pool(Duty.COS, [a, b, c, d]) == [a, b]
    assert pool(Duty.CDOS, [a, b, c, d]) == [d]


# --- TU slot mapping (P6 consumer; the TU Det Comd trap) -----------------------

def test_tu_slot_mapping_exact():
    assert TU_SLOT_APPOINTMENTS == {
        "TU_COMD": frozenset({Appointment.OC, Appointment.TWO_IC}),
        "TU_PLANNER": frozenset({Appointment.PC}),
        "TU_DET_COMD": frozenset({Appointment.P2IC, Appointment.PS}),
        "DET_PERSONNEL": frozenset({Appointment.DET_COMD, Appointment.OPR}),
    }


def test_tu_det_comd_trap_company_det_comd_fills_det_personnel_not_tu_det_comd():
    # The manning slot "TU Det Comd" is P2IC/PS by mapping — a company-
    # appointment Det Comd must NEVER satisfy it (regression-pinned per plan).
    assert Appointment.DET_COMD not in TU_SLOT_APPOINTMENTS["TU_DET_COMD"]
    assert Appointment.DET_COMD in TU_SLOT_APPOINTMENTS["DET_PERSONNEL"]
    assert Appointment.PS in TU_SLOT_APPOINTMENTS["TU_DET_COMD"]


# --- availability --------------------------------------------------------------

def test_any_covering_absence_blocks_including_pm_half_day():
    # Decision (d): anyone with ANY off/leave that day is skipped by auto-pick.
    p = person(Rank.CPL, Appointment.OPR)
    assert not available(p, DAY, absence_rows=[absence(day_part=DayPart.PM)])
    assert not available(p, DAY, absence_rows=[absence(day_part=DayPart.AM)])
    assert not available(p, DAY, absence_rows=[absence(start=DAY - timedelta(days=2),
                                                       end=DAY + timedelta(days=1))])


def test_non_covering_absence_does_not_block():
    p = person(Rank.CPL, Appointment.OPR)
    yesterday_only = absence(start=DAY - timedelta(days=1), end=DAY - timedelta(days=1))
    assert available(p, DAY, absence_rows=[yesterday_only])


def test_overnight_event_blocks_but_day_only_event_does_not():
    # v1's whole definition of outstation: the event model has no flag, so
    # overnight (end date after start date) IS the rule — stated, not guessed.
    p = person(Rank.CPL, Appointment.OPR)
    overnight = event(datetime(2026, 8, 4, 8, 0), datetime(2026, 8, 6, 17, 0))
    day_only = event(datetime(2026, 8, 5, 8, 0), datetime(2026, 8, 5, 22, 0))
    assert not available(p, DAY, overnight_events=[overnight])
    assert available(p, DAY, overnight_events=[day_only])


def test_overnight_event_not_covering_the_day_does_not_block():
    p = person(Rank.CPL, Appointment.OPR)
    next_week = event(datetime(2026, 8, 11, 8, 0), datetime(2026, 8, 13, 17, 0))
    assert available(p, DAY, overnight_events=[next_week])


def test_holding_the_other_duty_that_date_blocks():
    p = person(Rank.CPL, Appointment.OPR)
    assert not available(p, DAY, other_duty_dates={DAY})
    assert available(p, DAY, other_duty_dates={DAY + timedelta(days=1)})


def test_deactivated_person_is_never_available():
    p = person(Rank.CPL, Appointment.OPR, is_active=False)
    assert not available(p, DAY)


def test_no_rows_at_all_means_available():
    assert available(person(Rank.CPL, Appointment.OPR), DAY)


# --- eligibility uses the LEGAL rank order, never the parade display order -----

def test_eligibility_module_never_references_parade_rank_order():
    # AST-level, not raw-string: the docstring may EXPLAIN the rule by name,
    # but no code may import or use the parade display order.
    source = Path("app/domain/eligibility.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id != "PARADE_RANK_ORDER"
        elif isinstance(node, ast.ImportFrom):
            assert not node.module.startswith("flask"), node.module
            if node.module.startswith("app"):
                assert node.module.startswith("app.domain"), node.module
            for alias in node.names:
                assert alias.name != "PARADE_RANK_ORDER"
