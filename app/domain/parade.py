"""Parade display order + line format (Phase 3a). Pure: stdlib + domain
vocabulary only, so the ordering/format rules are testable without an app.

This module intentionally stays narrow — sort key and line format only.
Category compute and full-document rendering land in P3a.6.
"""
from app.domain.types import Appointment, Rank

# Decision (g): parade display order, NOT the SPEC.md chain of command (which
# lists SM above 2IC) — the owner's sample governs how the roster is printed.
# Decision (h): OC DES / CSM DES are not enum members yet; their slots are
# documented here as comments so the tuple below is correct on the day the
# unit actually creates those appointments.
_PARADE_APPOINTMENT_SEQUENCE = (
    Appointment.OC,
    # OC DES slots here (decision h) — not an enum member until Delta has one.
    Appointment.TWO_IC,
    Appointment.SM,
    # CSM DES slots here (decision h) — not an enum member until Delta has one.
    Appointment.PC,
    Appointment.P2IC,
    Appointment.PS,
    Appointment.DET_COMD,
    Appointment.OPR,
)
PARADE_APPOINTMENT_ORDER: dict = {
    appointment: idx for idx, appointment in enumerate(_PARADE_APPOINTMENT_SEQUENCE)
}

# Decision (g): 3WO is hoisted above LTA per the unit's own convention — this
# is display-only and deliberately diverges from the legal `RANK_ORDER` used
# for duty eligibility (see tests/test_parade_order.py). MSG and 1SG were
# unlisted in the original spec's rank line; they slot at their legal-order
# positions either side of SSG per the owner's decision.
_PARADE_RANK_SEQUENCE = (
    Rank.CPT,
    Rank.THREE_WO,
    Rank.LTA,
    Rank.TWO_LT,
    Rank.MSG,
    Rank.SSG,
    Rank.ONE_SG,
    Rank.TWO_SG,
    Rank.THREE_SG,
    Rank.CFC,
    Rank.CPL,
    Rank.LCP,
    Rank.PTE,
)
PARADE_RANK_ORDER: dict = {rank: idx for idx, rank in enumerate(_PARADE_RANK_SEQUENCE)}


def parade_sort_key(person) -> tuple:
    """Sort key for parade display: appointment, then rank, then platoon, then
    keyed (id) order — never alphabetical (owner's explicit "do not
    alphabetize" rule), so two same-rank people keep roster/creation order.
    """
    platoon_key = person.platoon or 0  # None (HQ/command team) sorts first.
    return (
        PARADE_APPOINTMENT_ORDER[person.appointment],
        PARADE_RANK_ORDER[person.rank],
        platoon_key,
        person.id,
    )


def parade_line(person) -> str:
    # display_name already embeds the rank prefix ("CPT Chan Wei Liang"), so
    # uppercasing it alone yields the required "RANK NAME" format.
    return person.display_name.upper()
