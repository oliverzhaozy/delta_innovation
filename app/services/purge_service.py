"""Annual retention purge (P7.2, amendment A10).

Every dated table is explicitly purged-or-kept; the inventory lives in
`docs/TECH_PLAN.md` and the plan. A row is purged only if it *fully ended
before* the cutoff `before` (a date): everything on/after `before` is kept, and
a row spanning the cutoff is kept. DateTime columns compare against
`datetime.combine(before, time.min)`.

The ledger is not merely deleted — old rows collapse per (person_id, kind) into
one carry-forward MANUAL row so every current balance is preserved exactly. The
balance-identity gate (A10) captures balances before and after all writes and
rolls back on any mismatch.

`plan` (read-only counts) and `execute` (single transaction) share ONE set of
private query builders, so the dry-run counts and the executed deletes can
never drift apart.
"""
from dataclasses import dataclass, field
from datetime import datetime, time

import click
from sqlalchemy import func

from app.domain.types import BalanceKind, LedgerSource
from app.extensions import db
from app.models import (
    DirectAbsence,
    DutyAssignment,
    Event,
    LeaveRequest,
    LedgerEntry,
    ManningPeriod,
    MealAdjustment,
    OverseasDeclaration,
    PersonAudit,
    RoDocument,
    StatusEntry,
)
from app.services import ledger_service


@dataclass
class PurgeResult:
    # Ordered (table_name, rows_removed) mirroring the A10 inventory order.
    counts: list = field(default_factory=list)
    # Nonzero (person_id, BalanceKind, half_day_sum) carry-forward rows.
    carry_forwards: list = field(default_factory=list)


def _bound(before):
    # A DateTime column's rows count as "before" only up to (not including)
    # midnight of the cutoff date — the single owning definition of the offset.
    return datetime.combine(before, time.min)


# --- row-set query builders: ONE definition each, used by plan and execute ---


def _ledger_old(before):
    return db.session.query(LedgerEntry).filter(LedgerEntry.created_at < _bound(before))


def _leave(before):
    # A10 FK edge: a leave row goes only if it ended before the cutoff AND no
    # SURVIVING ledger row still points at it. "Surviving" = created on/after
    # the cutoff — a value that is stable whether or not the old ledger rows
    # have been collapsed yet, so this builder is identical in plan and execute.
    surviving_refs = (
        db.session.query(LedgerEntry.leave_request_id)
        .filter(
            LedgerEntry.leave_request_id.isnot(None),
            LedgerEntry.created_at >= _bound(before),
        )
    )
    return db.session.query(LeaveRequest).filter(
        LeaveRequest.end_date < before,
        LeaveRequest.id.notin_(surviving_refs),
    )


def _status(before):
    return db.session.query(StatusEntry).filter(StatusEntry.end_date < before)


def _direct(before):
    return db.session.query(DirectAbsence).filter(DirectAbsence.end_date < before)


def _overseas(before):
    return db.session.query(OverseasDeclaration).filter(OverseasDeclaration.end_date < before)


def _events(before):
    return db.session.query(Event).filter(Event.end_dt < _bound(before))


def _duty_assignments(before):
    return db.session.query(DutyAssignment).filter(DutyAssignment.date < before)


def _ro_documents(before):
    return db.session.query(RoDocument).filter(RoDocument.date < before)


def _manning(before):
    return db.session.query(ManningPeriod).filter(ManningPeriod.end_date < before)


def _meals(before):
    return db.session.query(MealAdjustment).filter(MealAdjustment.date < before)


def _person_audit(before):
    return db.session.query(PersonAudit).filter(PersonAudit.at < _bound(before))


def _ledger_groups(before):
    # (person_id, kind, sum) over the old rows about to collapse; ordered so the
    # carry-forward summary is deterministic.
    return (
        db.session.query(
            LedgerEntry.person_id,
            LedgerEntry.kind,
            func.sum(LedgerEntry.delta_half_days),
        )
        .filter(LedgerEntry.created_at < _bound(before))
        .group_by(LedgerEntry.person_id, LedgerEntry.kind)
        .order_by(LedgerEntry.person_id, LedgerEntry.kind)
        .all()
    )


def _compute(before):
    counts = [
        ("ledger_entry", _ledger_old(before).count()),
        ("leave_request", _leave(before).count()),
        ("status_entry", _status(before).count()),
        ("direct_absence", _direct(before).count()),
        ("overseas_declaration", _overseas(before).count()),
        ("event", _events(before).count()),
        ("duty_assignment", _duty_assignments(before).count()),
        ("ro_document", _ro_documents(before).count()),
        ("manning_period", _manning(before).count()),
        ("meal_adjustment", _meals(before).count()),
        ("person_audit", _person_audit(before).count()),
    ]
    carry_forwards = [
        (person_id, kind, int(total)) for person_id, kind, total in _ledger_groups(before) if total
    ]
    return PurgeResult(counts=counts, carry_forwards=carry_forwards)


def _nonzero_balances():
    # A person whose balances are all zero is equivalent to a person absent from
    # the ledger; normalize so a zero-sum collapse (which drops the person's
    # rows entirely) is not misread as a balance change by the identity gate.
    raw = ledger_service.balances_for_everyone()
    return {
        person_id: kinds
        for person_id, kinds in raw.items()
        if any(v != 0 for v in kinds.values())
    }


def plan(before):
    """Read-only: what a purge with this cutoff WOULD remove. Touches no rows."""
    return _compute(before)


def execute(before, *, actor):
    """Perform the purge in one transaction, then commit. `actor` (keyword-only,
    no default) owns the carry-forward MANUAL rows. Rolls back and raises if the
    balance-identity gate fails."""
    result = _compute(before)
    before_balances = _nonzero_balances()

    # 1. Collapse the ledger first: delete the old rows, then re-post one
    #    MANUAL carry-forward per nonzero (person, kind). This must precede the
    #    leave delete — a leave row is only removable once no ledger row (old or
    #    new) still references it.
    _ledger_old(before).delete(synchronize_session=False)
    for person_id, kind, total in result.carry_forwards:
        db.session.add(
            LedgerEntry(
                person_id=person_id,
                kind=kind,
                delta_half_days=total,
                reason=f"Carry-forward (purge --before {before.isoformat()})",
                source=LedgerSource.MANUAL,
                leave_request_id=None,
                created_by_id=actor.id,
            )
        )

    # 2. Leave rows with no surviving ledger reference (A10 FK edge).
    _leave(before).delete(synchronize_session=False)

    # 3. Remaining leaf tables (nothing FKs into these).
    _status(before).delete(synchronize_session=False)
    _direct(before).delete(synchronize_session=False)
    _overseas(before).delete(synchronize_session=False)
    _duty_assignments(before).delete(synchronize_session=False)
    _meals(before).delete(synchronize_session=False)
    _person_audit(before).delete(synchronize_session=False)

    # 4. Parents with delete-orphan children — delete via ORM objects so the
    #    cascade fires (per-object is fine at ~36-person annual volume).
    for event in _events(before).all():
        db.session.delete(event)
    for document in _ro_documents(before).all():
        db.session.delete(document)
    for period in _manning(before).all():
        db.session.delete(period)

    # 5. Balance-identity gate (A10): balances must be byte-identical.
    db.session.flush()
    after_balances = _nonzero_balances()
    if after_balances != before_balances:
        db.session.rollback()
        raise click.ClickException(
            "Balance identity check failed after collapse; purge rolled back."
        )

    db.session.commit()
    return result
