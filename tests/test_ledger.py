from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import (
    BalanceKind,
    DayPart,
    LeaveType,
    LedgerSource,
    RequestStatus,
)
from app.extensions import db
from app.models import LeaveRequest, Person
from app.services import ledger_service


def test_balance_is_sum_of_entries(app, make_person):
    make_person(username="bal1")
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="bal1").scalar()
        ledger_service.post_entry(
            person_id=pid, kind=BalanceKind.OFF, delta_half_days=6,
            reason="opening balance", source=LedgerSource.MANUAL, created_by_id=pid,
        )
        ledger_service.post_entry(
            person_id=pid, kind=BalanceKind.OFF, delta_half_days=-2,
            reason="1 day off", source=LedgerSource.MANUAL, created_by_id=pid,
        )
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OFF) == 4
        assert ledger_service.balance(pid, BalanceKind.OIL) == 0


def test_balance_can_go_negative(app, make_person):
    make_person(username="bal2")
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="bal2").scalar()
        ledger_service.post_entry(
            person_id=pid, kind=BalanceKind.OIL, delta_half_days=-3,
            reason="deduction", source=LedgerSource.MANUAL, created_by_id=pid,
        )
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OIL) == -3


def test_double_approval_rows_blocked_by_unique_constraint(app, make_person):
    make_person(username="bal3")
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="bal3").scalar()
        req = LeaveRequest(
            person_id=pid, type=LeaveType.OFF, start_date=date(2026, 7, 8),
            end_date=date(2026, 7, 8), status=RequestStatus.APPROVED,
        )
        db.session.add(req)
        db.session.flush()
        for _ in range(2):
            ledger_service.post_entry(
                person_id=pid, kind=BalanceKind.OFF, delta_half_days=-2,
                reason="off", source=LedgerSource.LEAVE_APPROVAL,
                created_by_id=pid, leave_request_id=req.id,
            )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_multiple_manual_entries_allowed(app, make_person):
    # NULL leave_request_id rows must not collide on the uniqueness backstop.
    make_person(username="bal4")
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="bal4").scalar()
        for delta in (2, 2):
            ledger_service.post_entry(
                person_id=pid, kind=BalanceKind.OFF, delta_half_days=delta,
                reason="award", source=LedgerSource.MANUAL, created_by_id=pid,
            )
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OFF) == 4


def test_half_day_constraint_enforced_in_db(app, make_person):
    make_person(username="bal5")
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="bal5").scalar()
        req = LeaveRequest(
            person_id=pid, type=LeaveType.OFF, start_date=date(2026, 7, 8),
            end_date=date(2026, 7, 9), day_part=DayPart.AM,
            status=RequestStatus.PENDING_PC,
        )
        db.session.add(req)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
