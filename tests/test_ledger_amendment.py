"""P2.9 ledger groundwork for amendment.

Covers the two changes that must land together: the approval-scoped partial
unique index (REVERSAL multiplicity becomes legitimate) and the net-outstanding
cancel credit (no over-credit after a partial reversal). See the P2.9 brief.
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import BalanceKind, LeaveType, LedgerSource, RequestStatus
from app.extensions import db
from app.models import LedgerEntry, LeaveRequest, Person
from app.services import ledger_service
from app.services.approval_service import TransitionError, cancel_approved


def _pid(username):
    return db.session.query(Person.id).filter_by(username=username).scalar()


def _approved_request(person_id):
    """A committed, APPROVED 3-working-day OFF request (no ledger rows yet)."""
    req = LeaveRequest(
        person_id=person_id,
        type=LeaveType.OFF,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
        status=RequestStatus.APPROVED,
    )
    db.session.add(req)
    db.session.flush()
    return req


def _debit(person_id, req_id, actor_id, delta):
    ledger_service.post_entry(
        person_id=person_id, kind=BalanceKind.OFF, delta_half_days=delta,
        reason="OFF Wed 08 Jul", source=LedgerSource.LEAVE_APPROVAL,
        created_by_id=actor_id, leave_request_id=req_id,
    )


def _reversal(person_id, req_id, actor_id, delta):
    ledger_service.post_entry(
        person_id=person_id, kind=BalanceKind.OFF, delta_half_days=delta,
        reason="Early return", source=LedgerSource.REVERSAL,
        created_by_id=actor_id, leave_request_id=req_id,
    )


def test_partial_reversal_then_cancel_credits_only_remainder(app, make_person):
    """Debit -6, an early-return REVERSAL +4 already posted -> cancel credits +2 only."""
    make_person(username="amend1")
    make_person(username="s3_a1")
    with app.app_context():
        pid, actor_id = _pid("amend1"), _pid("s3_a1")
        req = _approved_request(pid)
        _debit(pid, req.id, actor_id, -6)
        _reversal(pid, req.id, actor_id, 4)  # simulates P2.10 early return
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OFF) == -2

        cancel_approved(req, db.session.get(Person, actor_id))

        assert db.session.get(LeaveRequest, req.id).status is RequestStatus.CANCELLED
        # Net outstanding was -2, so exactly +2 is credited: balance restored to 0.
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0
        rows = db.session.query(LedgerEntry).filter_by(leave_request_id=req.id).all()
        assert len(rows) == 3  # append-only: original debit, +4, +2 — nothing edited
        cancel_credits = [r for r in rows if r.source is LedgerSource.REVERSAL and r.delta_half_days == 2]
        assert len(cancel_credits) == 1


def test_fully_reversed_then_cancel_posts_nothing(app, make_person):
    """Debit -6 fully reversed +6 -> cancel posts no row but still flips to CANCELLED."""
    make_person(username="amend2")
    make_person(username="s3_a2")
    with app.app_context():
        pid, actor_id = _pid("amend2"), _pid("s3_a2")
        req = _approved_request(pid)
        _debit(pid, req.id, actor_id, -6)
        _reversal(pid, req.id, actor_id, 6)  # already fully returned
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0

        cancel_approved(req, db.session.get(Person, actor_id))

        assert db.session.get(LeaveRequest, req.id).status is RequestStatus.CANCELLED
        rows = db.session.query(LedgerEntry).filter_by(leave_request_id=req.id).all()
        assert len(rows) == 2  # net was 0 -> nothing posted for the kind
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0


def test_second_approval_debit_still_violates_index(app, make_person):
    """One approval debit per request+kind is still enforced (double-deduction backstop)."""
    make_person(username="amend3")
    with app.app_context():
        pid = _pid("amend3")
        req = _approved_request(pid)
        _debit(pid, req.id, pid, -2)
        _debit(pid, req.id, pid, -2)  # second LEAVE_APPROVAL row, same request+kind
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_two_reversal_rows_for_same_request_kind_allowed(app, make_person):
    """The exact relaxation: multiple REVERSAL rows per request+kind are legitimate."""
    make_person(username="amend4")
    with app.app_context():
        pid = _pid("amend4")
        req = _approved_request(pid)
        _debit(pid, req.id, pid, -6)
        _reversal(pid, req.id, pid, 4)
        _reversal(pid, req.id, pid, 2)  # would violate the OLD constraint
        db.session.commit()  # must NOT raise
        rows = db.session.query(LedgerEntry).filter_by(leave_request_id=req.id).all()
        assert len(rows) == 3
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0


def test_double_cancel_dies_at_claim(app, make_person):
    """Double-cancel protection lives in _claim, not the constraint: no double credit."""
    make_person(username="amend5")
    make_person(username="s3_a5")
    with app.app_context():
        pid, actor_id = _pid("amend5"), _pid("s3_a5")
        req = _approved_request(pid)
        _debit(pid, req.id, actor_id, -6)
        db.session.commit()

        cancel_approved(req, db.session.get(Person, actor_id))
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0

        with pytest.raises(TransitionError):
            cancel_approved(req, db.session.get(Person, actor_id))
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0  # unchanged


def test_manual_entries_remain_unlimited(app, make_person):
    """NULL leave_request_id rows are outside the approval-scoped index entirely."""
    make_person(username="amend6")
    with app.app_context():
        pid = _pid("amend6")
        for _ in range(3):
            ledger_service.post_entry(
                person_id=pid, kind=BalanceKind.OFF, delta_half_days=2,
                reason="award", source=LedgerSource.MANUAL, created_by_id=pid,
            )
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OFF) == 6
