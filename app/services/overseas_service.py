"""Overseas-declaration lifecycle (owner directive 2026-07-28).

Same posture as approval_service: this module owns the transactions, and every
decision claims the row with a conditional UPDATE (rowcount == 1 or abort), so
two PCs clicking at once cannot both action one declaration. TransitionError is
imported rather than redefined — the routes catch ONE exception type for both
approval flows.
"""
from sqlalchemy import delete, update

from app.domain.dates import now_sgt, today_sgt
from app.domain.types import DeclarationStatus
from app.extensions import db
from app.models import OverseasDeclaration
from app.services.approval_service import TransitionError


def purge_expired() -> int:
    """Delete every declaration whose end_date has passed; returns the count.

    Called at the top of each overseas page: there are no background workers in
    this app (CLAUDE.md), so "the entry disappears once the trip is over" is
    enforced on read.
    """
    result = db.session.execute(
        delete(OverseasDeclaration).where(OverseasDeclaration.end_date < today_sgt())
    )
    db.session.commit()
    return result.rowcount


def _claim(declaration_id, **values):
    """Atomically move the row out of PENDING; fail if someone got there first."""
    result = db.session.execute(
        update(OverseasDeclaration)
        .where(
            OverseasDeclaration.id == declaration_id,
            OverseasDeclaration.status == DeclarationStatus.PENDING,
        )
        .values(**values)
    )
    if result.rowcount != 1:
        db.session.rollback()
        raise TransitionError("This declaration was already actioned by someone else.")


def _forbid_self_action(declaration, actor):
    # Belt and braces: a PC's own declaration is auto-APPROVED so it is never
    # PENDING, but the guard outlives any future routing change.
    if declaration.person_id == actor.id:
        raise TransitionError("You cannot action your own declaration.")


def pc_approve(declaration, actor):
    _forbid_self_action(declaration, actor)
    _claim(
        declaration.id,
        status=DeclarationStatus.APPROVED,
        pc_actor_id=actor.id,
        pc_at=now_sgt(),
    )
    db.session.commit()


def pc_reject(declaration, actor, remarks):
    _forbid_self_action(declaration, actor)
    remark = (remarks or "").strip()
    if not remark:
        raise TransitionError("A short remark is required when rejecting.")
    _claim(
        declaration.id,
        status=DeclarationStatus.REJECTED,
        pc_actor_id=actor.id,
        pc_at=now_sgt(),
        remarks=remark,
    )
    db.session.commit()
