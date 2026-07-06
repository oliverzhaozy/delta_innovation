"""Leave request state transitions.

Every transition claims the row with a conditional UPDATE (rowcount == 1 or
abort), so double-clicks and concurrent approvals cannot double-apply. OC
approval writes status flip + ledger debit in ONE transaction — commit or
nothing. This function IS the product's core promise: approving is what plots
the absence and decrements the balance, atomically.
"""
from sqlalchemy import func, update

from app.domain.dates import now_sgt
from app.domain.types import BalanceKind, DayPart, LedgerSource, RequestStatus
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


def _claim_end_date(request_id, old_end, new_end):
    """Sibling of _claim for early return: pins end_date as well as status, so a
    concurrent or repeated amendment (the row already moved) matches 0 rows and
    loses cleanly instead of double-crediting."""
    result = db.session.execute(
        update(LeaveRequest)
        .where(
            LeaveRequest.id == request_id,
            LeaveRequest.status == RequestStatus.APPROVED,
            LeaveRequest.end_date == old_end,
        )
        .values(end_date=new_end)
    )
    if result.rowcount != 1:
        db.session.rollback()
        raise TransitionError("This request is no longer approved, or was already amended.")


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

    Credit the NET OUTSTANDING per kind, not a mirror of the original debit: an
    earlier amendment (early return) may already have posted a partial reversal,
    so we only restore what is still deducted (net = SUM of every row for this
    request). Mirroring the debit would over-credit and drift the balance.
    """
    _claim(request.id, RequestStatus.APPROVED, status=RequestStatus.CANCELLED)
    try:
        from app.models import LedgerEntry  # local import to avoid cycle at module load

        outstanding = (
            db.session.query(
                LedgerEntry.person_id,
                LedgerEntry.kind,
                func.sum(LedgerEntry.delta_half_days),
            )
            .filter_by(leave_request_id=request.id)
            .group_by(LedgerEntry.person_id, LedgerEntry.kind)
            .all()
        )
        for person_id, kind, net in outstanding:
            # net < 0 means half-days are still deducted; credit exactly that
            # remainder. net == 0 (fully reversed already) posts nothing.
            if net < 0:
                ledger_service.post_entry(
                    person_id=person_id,
                    kind=kind,
                    delta_half_days=-net,
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


def early_return(request, actor, new_end_date):
    """Shorten an APPROVED full-day multi-day request to an earlier last day and
    credit the balance for the working days no longer taken — status flip + one
    compensating REVERSAL in one transaction, ledger never edited.

    Credit is net-from-ledger, NOT a recompute of the original debit: a
    public-holiday table edit since approval could change the original cost, so
    we credit (outstanding still deducted) − (recomputed cost of the shortened
    range), clamped at zero. This mirrors cancel_approved's net-outstanding
    idiom, so a second amendment or a later cancel each compose without drift.
    """
    # Eligibility guards (the status guard is the conditional claim itself).
    if request.day_part is not DayPart.FULL:
        raise TransitionError("Early return applies to full-day leave only.")
    if request.end_date <= request.start_date:
        raise TransitionError("Early return applies to multi-day leave only.")
    if not (request.start_date <= new_end_date < request.end_date):
        raise TransitionError(
            "The new last day must be on or after the start and before the current end."
        )

    old_end = request.end_date
    _claim_end_date(request.id, old_end, new_end_date)
    try:
        from app.models import LedgerEntry  # local import to avoid cycle at module load

        # The claim already synced request.end_date, so this is the SHORTENED cost
        # against the current PH table (working days only). LL/OL cost 0.
        new_cost = leave_service.deduction_half_days(request)
        # A leave request has ledger rows of exactly one kind (its type), so this
        # net-per-kind sum (mirroring the P2.9 cancel query) yields one group for
        # balance-tracked types and none for LL/OL.
        outstanding = (
            db.session.query(
                LedgerEntry.person_id,
                LedgerEntry.kind,
                func.sum(LedgerEntry.delta_half_days),
            )
            .filter_by(leave_request_id=request.id)
            .group_by(LedgerEntry.person_id, LedgerEntry.kind)
            .all()
        )
        for person_id, kind, net in outstanding:
            # -net = half-days still deducted; credit only the excess over the
            # shortened cost. Clamp at 0 so an already-reversed request posts nothing.
            credit = max(0, -net - new_cost)
            if credit > 0:
                ledger_service.post_entry(
                    person_id=person_id,
                    kind=kind,
                    delta_half_days=credit,
                    reason=(
                        f"Early return: {request.type.value} "
                        f"{request.start_date.strftime('%d %b')}–{old_end.strftime('%d %b')} "
                        f"→ end {new_end_date.strftime('%d %b')}"
                    ),
                    source=LedgerSource.REVERSAL,
                    created_by_id=actor.id,
                    leave_request_id=request.id,
                )
        db.session.commit()
    except TransitionError:
        raise
    except Exception:
        db.session.rollback()  # no partial state, ever
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
