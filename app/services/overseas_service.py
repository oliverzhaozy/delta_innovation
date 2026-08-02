"""Overseas-declaration lifecycle (owner directive 2026-07-28).

Same posture as approval_service: this module owns the transactions, and every
decision claims the row with a conditional UPDATE (rowcount == 1 or abort), so
two PCs clicking at once cannot both action one declaration. TransitionError is
imported rather than redefined — the routes catch ONE exception type for both
approval flows.
"""
from collections import defaultdict

from sqlalchemy import delete, update

from app.domain.dates import now_sgt, today_sgt
from app.domain.types import DeclarationStatus
from app.extensions import db
from app.models import ManningPeriod, ManningSlot, OverseasDeclaration, Person
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


def pc_reject(declaration, actor):
    # No remark (owner 2026-08-02, reversing part of decision (y)): the PC just
    # rejects; the `remarks` column stays only so legacy rows keep displaying.
    _forbid_self_action(declaration, actor)
    _claim(
        declaration.id,
        status=DeclarationStatus.REJECTED,
        pc_actor_id=actor.id,
        pc_at=now_sgt(),
    )
    db.session.commit()


def pending_declarations():
    """Declarations awaiting a PC, most upcoming travel first (matching the
    leave queues' ordering) — the ONE query behind the PC queue page and the
    dashboard's travel card.

    Callers run `purge_expired()` first: an elapsed declaration is deleted, not
    filtered out, so the purge is what keeps this list honest.
    """
    return (
        db.session.query(OverseasDeclaration)
        .join(Person, OverseasDeclaration.person_id == Person.id)
        .filter(OverseasDeclaration.status == DeclarationStatus.PENDING)
        .order_by(OverseasDeclaration.start_date)
        .all()
    )


def rejected_declarations_for(person_id):
    """This person's rejected declarations whose dates have not yet passed —
    the declarant-facing counterpart of `pending_declarations`.

    Filtered, not purged: the pages that read this are read-only for a
    non-PC viewer, so an elapsed row no overseas page has swept yet is skipped
    here rather than deleted; `purge_expired()` stays the one place rows die.
    """
    return (
        db.session.query(OverseasDeclaration)
        .filter(
            OverseasDeclaration.person_id == person_id,
            OverseasDeclaration.status == DeclarationStatus.REJECTED,
            OverseasDeclaration.end_date >= today_sgt(),
        )
        .order_by(OverseasDeclaration.start_date)
        .all()
    )


def on_manning_ids(declarations):
    """IDs of declarations whose person holds a TU manning slot in a period
    overlapping the declared dates. Every period status counts — approval
    gates nothing operationally (ManningStatus), so even a DRAFT assignment
    is a commitment the deciding PC should see.
    """
    if not declarations:
        return set()
    periods = defaultdict(list)
    rows = (
        db.session.query(
            ManningSlot.person_id, ManningPeriod.start_date, ManningPeriod.end_date
        )
        .join(ManningPeriod, ManningSlot.period_id == ManningPeriod.id)
        .all()
    )
    for person_id, start, end in rows:
        periods[person_id].append((start, end))
    return {
        d.id
        for d in declarations
        if any(
            start <= d.end_date and d.start_date <= end
            for start, end in periods.get(d.person_id, ())
        )
    }
