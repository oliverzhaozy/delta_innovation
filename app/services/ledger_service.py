"""Ledger reads and writes. Writes only ADD rows to the session — the caller
owns the transaction, so approval can commit status + ledger atomically.
"""
from sqlalchemy import func

from app.domain.types import BalanceKind
from app.extensions import db
from app.models import LedgerEntry


def balance(person_id: int, kind: BalanceKind) -> int:
    """Current balance in half-days: SUM of the append-only ledger."""
    return (
        db.session.query(func.coalesce(func.sum(LedgerEntry.delta_half_days), 0))
        .filter_by(person_id=person_id, kind=kind)
        .scalar()
    )


def balances(person_id: int) -> dict:
    return {kind: balance(person_id, kind) for kind in BalanceKind}


def balances_for_everyone() -> dict:
    """{person_id: {BalanceKind: half_days}} for all people with any entries."""
    rows = (
        db.session.query(
            LedgerEntry.person_id,
            LedgerEntry.kind,
            func.sum(LedgerEntry.delta_half_days),
        )
        .group_by(LedgerEntry.person_id, LedgerEntry.kind)
        .all()
    )
    out: dict = {}
    for person_id, kind, total in rows:
        out.setdefault(person_id, {k: 0 for k in BalanceKind})[kind] = total
    return out


def post_entry(*, person_id, kind, delta_half_days, reason, source, created_by_id, leave_request_id=None):
    """Append one ledger row to the session (no commit — caller's transaction)."""
    entry = LedgerEntry(
        person_id=person_id,
        kind=kind,
        delta_half_days=delta_half_days,
        reason=reason,
        source=source,
        leave_request_id=leave_request_id,
        created_by_id=created_by_id,
    )
    db.session.add(entry)
    return entry


def history(person_id: int):
    return (
        db.session.query(LedgerEntry)
        .filter_by(person_id=person_id)
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .all()
    )
