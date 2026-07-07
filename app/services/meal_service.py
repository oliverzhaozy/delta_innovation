"""Meal-count assembly (P3b.6): derive the three parade docs through
parade_service.build_doc — the ONE document pipeline (pre-flight addendum A2),
so meals can never disagree with the parade pages — sum the append-only
MealAdjustment rows per meal, and hand both to the pure domain compute.
"""
from datetime import timedelta

from sqlalchemy import func

from app.domain import meals as meals_domain
from app.domain.types import ParadeVariant
from app.extensions import db
from app.models import MealAdjustment
from app.services import parade_service


def adjustments_for(day):
    """{Meal: summed delta} for `day` — pre-summed so the pure module never
    sees DB rows (its contract)."""
    rows = (
        db.session.query(MealAdjustment.meal, func.sum(MealAdjustment.delta))
        .filter(MealAdjustment.date == day)
        .group_by(MealAdjustment.meal)
        .all()
    )
    return {meal: total for meal, total in rows}


def adjustment_rows(day):
    """Full keyed history for the page, oldest first — the rows ARE the audit
    trail (append-only; corrections are compensating rows, never edits)."""
    return (
        db.session.query(MealAdjustment)
        .filter(MealAdjustment.date == day)
        .order_by(MealAdjustment.created_at, MealAdjustment.id)
        .all()
    )


def compute_for(day):
    """(counts, imbalance) for day D. Offsets per domain/meals: breakfast reads
    roll_call(D), lunch morning(D), dinner roll_call(D+1). If ANY of the three
    docs is refused by the engine, the counts are refused too — a wrong food
    order is worse than none (same posture as the parade pages).
    """
    rc_today = parade_service.build_doc(day, ParadeVariant.ROLL_CALL)
    morning = parade_service.build_doc(day, ParadeVariant.MORNING)
    rc_next = parade_service.build_doc(day + timedelta(days=1), ParadeVariant.ROLL_CALL)
    imbalance = rc_today.imbalance or morning.imbalance or rc_next.imbalance
    if imbalance:
        return None, imbalance
    counts = meals_domain.compute_meals(
        day, rc_today.doc, morning.doc, rc_next.doc, adjustments_for(day)
    )
    return counts, None


def add_adjustment(day, meal, delta, reason, actor) -> MealAdjustment:
    row = MealAdjustment(
        date=day, meal=meal, delta=delta, reason=reason, created_by_id=actor.id
    )
    db.session.add(row)
    db.session.commit()
    return row
