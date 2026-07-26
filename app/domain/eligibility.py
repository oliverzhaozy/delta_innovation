"""Assignment eligibility: who can be PICKED for a duty or manning slot (P4.2).

The OTHER permission concept — policy.py answers what a logged-in person may
see and do; this module answers who may legally hold an assignment. Keep them
separate (plan: the two are easy to conflate and must not be).

Public API is FROZEN (pre-flight addendum B4) — P6's manning code imports these
five names without reading P4 code:

    eligible_cos(p) · eligible_cdos(p) · pool(duty, people)
    TU_SLOT_APPOINTMENTS · available(p, day, *, absence_rows=(),
                                     overnight_events=(), other_duty_dates=())

Rank comparisons use the LEGAL RANK_ORDER (rank_at_most/rank_at_least), never
PARADE_RANK_ORDER — eligibility is law, display order is convention. Pure
module: stdlib + sibling app.domain only; callers pre-shape all rows.
"""
from app.domain.presence import covers
from app.domain.types import Appointment, Duty, Rank, rank_at_least, rank_at_most

# Manning slot -> the appointments that may fill it (P6 consumer, landed here
# because one module owns "who can be picked"). Keys are the future
# ManningSlotType values (P6.2), kept as strings until that enum exists.
# THE TRAP, schema-level: the slot "TU Det Comd" is filled by appointment
# P2IC/PS — a company-appointment Det Comd fills DET_PERSONNEL, never
# TU_DET_COMD. Regression-pinned in tests.
TU_SLOT_APPOINTMENTS = {
    "TU_COMD": frozenset({Appointment.OC, Appointment.TWO_IC}),
    "TU_PLANNER": frozenset({Appointment.PC}),
    "TU_DET_COMD": frozenset({Appointment.P2IC, Appointment.PS}),
    "DET_PERSONNEL": frozenset({Appointment.DET_COMD, Appointment.OPR}),
}

_COS_APPOINTMENTS = frozenset({Appointment.DET_COMD, Appointment.OPR})
_CDOS_APPOINTMENTS = frozenset({Appointment.PC, Appointment.P2IC, Appointment.PS})
# 2SG legally sits in BOTH rank ranges; the disjoint appointment sets are what
# make dual-eligibility structurally impossible (pinned exhaustively in tests).


def eligible_cos(p) -> bool:
    """COS: rank 2SG or below AND appointment Det Comd or Opr."""
    return rank_at_most(p.rank, Rank.TWO_SG) and p.appointment in _COS_APPOINTMENTS


def eligible_cdos(p) -> bool:
    """CDO/S: rank 2SG or above AND appointment PC, P2IC, or PS."""
    return rank_at_least(p.rank, Rank.TWO_SG) and p.appointment in _CDOS_APPOINTMENTS


def pool(duty, people) -> list:
    """The computed candidate pool for one duty: eligible AND active AND not
    duty_exempt (the per-person carve-out is data, not law — the rank/
    appointment rules above stay pure), roster order preserved. Always
    displayed on the roster page — an accidentally tiny/empty pool must be
    visible immediately (the 3SG-PS gap is real)."""
    rule = eligible_cos if duty is Duty.COS else eligible_cdos
    return [p for p in people if p.is_active and not p.duty_exempt and rule(p)]


def available(p, day, *, absence_rows=(), overnight_events=(), other_duty_dates=()) -> bool:
    """Can this person actually take a duty on `day`? Pure over pre-shaped
    rows the caller fetched:

    - `absence_rows`: this person's approved leaves / direct absences /
      blocking statuses. ANY covering row of ANY day_part blocks (decision d —
      a PM half-day still skips auto-pick; the PS may override with a warning).
    - `overnight_events`: TP events this person is tagged in. Only an
      OVERNIGHT event blocks (end date after start date) — the event model has
      no outstation flag, so this derived rule is v1's whole definition.
    - `other_duty_dates`: dates this person already holds the other duty.
    """
    if not p.is_active:
        return False
    if any(covers(row, day) for row in absence_rows):
        return False
    for ev in overnight_events:
        if ev.end_dt.date() > ev.start_dt.date() and ev.start_dt.date() <= day <= ev.end_dt.date():
            return False
    return day not in other_duty_dates
