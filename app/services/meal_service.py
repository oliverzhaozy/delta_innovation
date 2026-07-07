"""NSF presence counters for the S4 page (owner decision (j), 2026-07-07):
derive morning(D) and roll_call(D+1) through parade_service.build_doc — the
ONE document pipeline (pre-flight addendum A2), so the counters can never
disagree with the parade pages — and hand both docs to the pure domain compute.
"""
from datetime import timedelta

from app.domain import meals as meals_domain
from app.domain.types import ParadeVariant
from app.services import parade_service


def compute_for(day):
    """(NsfPresence, imbalance) for day D. If either doc is refused by the
    engine the counters are refused too — a wrong indent number is worse than
    none (same posture as the parade pages)."""
    morning = parade_service.build_doc(day, ParadeVariant.MORNING)
    rc_next = parade_service.build_doc(day + timedelta(days=1), ParadeVariant.ROLL_CALL)
    imbalance = morning.imbalance or rc_next.imbalance
    if imbalance:
        return None, imbalance
    return meals_domain.nsf_presence(morning.doc, rc_next.doc), None
