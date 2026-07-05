"""Leave request state transitions.

Every transition claims the row with a conditional UPDATE (rowcount == 1 or
abort), so double-clicks and concurrent approvals cannot double-apply. OC
approval writes status flip + ledger debit in ONE transaction — commit or
nothing. This function IS the product's core promise: approving is what plots
the absence and decrements the balance, atomically.
"""
from sqlalchemy import update

from app.domain.dates import now_sgt
from app.domain.types import BalanceKind, LedgerSource, RequestStatus
from app.extensions import db
from app.models import LeaveRequest
from app.services import ledger_service, leave_service


class TransitionError(Exception):
    """The transition is not allowed; message is user-facing."""


class NegativeBalanceUnconfirmed(Exception):
    """Approval would take the balance negative; the OC must explicitly confirm."""

    def __init__(self, projected_half_days):
        super().__init__("projected negative balance")
        self.projected_half_days = projected_half_days


def _claim(request_id, from_status, **values):
    """Atomically move the row out of from_status; fail if someone got there first."""
    result = db.session.execute(
        update(LeaveRequest)
        .where(LeaveRequest.id == request_id, LeaveRequest.status == from_status)
        .values(**values)
    )
    if result.rowcount != 1:
        db.session.rollback()
        raise TransitionError("This request was already actioned by someone else.")


def _forbid_self_action(request, actor):
    if request.person_id == actor.id:
        raise TransitionError("You cannot action your own request.")


def pc_approve(request, actor):
    _forbid_self_action(request, actor)
    _claim(
        request.id,
        RequestStatus.PENDING_PC,
        status=RequestStatus.PENDING_OC,
        pc_actor_id=actor.id,
        pc_at=now_sgt(),
    )
    db.session.commit()


def pc_reject(request, actor, remark):
    _forbid_self_action(request, actor)
    _claim(
        request.id,
        RequestStatus.PENDING_PC,
        status=RequestStatus.REJECTED_PC,
        pc_actor_id=actor.id,
        pc_at=now_sgt(),
        remarks=remark,
    )
    db.session.commit()


def oc_reject(request, actor, remark):
    _forbid_self_action(request, actor)
    _claim(
        request.id,
        RequestStatus.PENDING_OC,
        status=RequestStatus.REJECTED_OC,
        oc_actor_id=actor.id,
        oc_at=now_sgt(),
        remarks=remark,
    )
    db.session.commit()


def cancel_approved(request, actor):
    """Cancel APPROVED leave: status flip + compensating REVERSAL credit in one
    transaction. The ledger is append-only — the original debit stays, the
    reversal explains itself, and the balance is whole again.
    """
    _claim(request.id, RequestStatus.APPROVED, status=RequestStatus.CANCELLED)
    try:
        from app.models import LedgerEntry  # local import to avoid cycle at module load

        originals = (
            db.session.query(LedgerEntry)
            .filter_by(leave_request_id=request.id, source=LedgerSource.LEAVE_APPROVAL)
            .all()
        )
        for entry in originals:
            ledger_service.post_entry(
                person_id=entry.person_id,
                kind=entry.kind,
                delta_half_days=-entry.delta_half_days,
                reason=f"Cancelled: {request.type.value} {request.when_label}",
                source=LedgerSource.REVERSAL,
                created_by_id=actor.id,
                leave_request_id=request.id,
            )
        db.session.commit()
    except TransitionError:
        raise
    except Exception:
        db.session.rollback()
        raise


def oc_approve(request, actor, confirm_negative=False):
    """Final approval: status + ledger in one transaction."""
    _forbid_self_action(request, actor)
    _claim(
        request.id,
        RequestStatus.PENDING_OC,
        status=RequestStatus.APPROVED,
        oc_actor_id=actor.id,
        oc_at=now_sgt(),
    )
    try:
        # Re-checked INSIDE the transaction: state may have changed since the
        # OC loaded the page (another approval, an S3 deduction).
        conflict = leave_service.day_part_conflict(request.person_id, request)
        if conflict:
            db.session.rollback()
            raise TransitionError(
                f"Blocked: an approved request already covers {conflict.when_label} — "
                "approving this too would double-count the same day-part."
            )
        cost = leave_service.deduction_half_days(request)
        if cost:
            kind = BalanceKind(request.type.value)
            projected = ledger_service.balance(request.person_id, kind) - cost
            if projected < 0 and not confirm_negative:
                db.session.rollback()
                raise NegativeBalanceUnconfirmed(projected)
            ledger_service.post_entry(
                person_id=request.person_id,
                kind=kind,
                delta_half_days=-cost,
                reason=f"{request.type.value} {request.when_label}",
                source=LedgerSource.LEAVE_APPROVAL,
                created_by_id=actor.id,
                leave_request_id=request.id,
            )
        db.session.commit()
    except (TransitionError, NegativeBalanceUnconfirmed):
        raise  # already rolled back
    except Exception:
        db.session.rollback()  # no partial state, ever
        raise
