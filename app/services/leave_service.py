"""Leave request queries and deduction math (the DB-aware glue around the pure
domain helpers).
"""
from app.domain.dates import is_working_day, today_sgt, working_days
from app.domain.types import (
    BALANCE_TRACKED,
    DayPart,
    OCCUPYING_STATUSES,
    PENDING_STATUSES,
    RequestStatus,
)
from app.extensions import db
from app.models import LeaveRequest, PublicHoliday

# Statuses that end a request's life without it ever elapsing.
DECIDED_AGAINST_STATUSES = frozenset(
    {RequestStatus.REJECTED_PC, RequestStatus.REJECTED_OC, RequestStatus.CANCELLED}
)


def live_requests(person_id):
    """This person's still-open requests: awaiting a decision, or approved leave
    not yet elapsed (same predicate as the admin pre-delete warning). Pending rows
    whose dates already passed stay live — nobody has decided them yet.
    """
    return (
        db.session.query(LeaveRequest)
        .filter(
            LeaveRequest.person_id == person_id,
            db.or_(
                LeaveRequest.status.in_(PENDING_STATUSES),
                db.and_(
                    LeaveRequest.status == RequestStatus.APPROVED,
                    LeaveRequest.end_date >= today_sgt(),
                ),
            ),
        )
        .order_by(LeaveRequest.start_date, LeaveRequest.created_at)
        .all()
    )


def concluded_requests(person_id):
    """The exact complement of live_requests — rejected, cancelled, or approved
    leave already taken. History is a DISPLAY split only: rows are never moved or
    deleted (approved ones are the source of truth behind ledger entries).
    """
    return (
        db.session.query(LeaveRequest)
        .filter(
            LeaveRequest.person_id == person_id,
            db.or_(
                LeaveRequest.status.in_(DECIDED_AGAINST_STATUSES),
                db.and_(
                    LeaveRequest.status == RequestStatus.APPROVED,
                    LeaveRequest.end_date < today_sgt(),
                ),
            ),
        )
        .order_by(LeaveRequest.start_date.desc())
        .all()
    )


def overlapping_requests(person_id, start_date, end_date, exclude_id=None):
    """This person's pending/approved requests touching [start, end]."""
    q = (
        db.session.query(LeaveRequest)
        .filter(
            LeaveRequest.person_id == person_id,
            LeaveRequest.status.in_(OCCUPYING_STATUSES),
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date,
        )
        .order_by(LeaveRequest.start_date)
    )
    if exclude_id is not None:
        q = q.filter(LeaveRequest.id != exclude_id)
    return q.all()


def day_part_conflict(person_id, request):
    """An APPROVED request of this person covering the same day-part — the one
    overlap that is hard-blocked at approval (it would double-deduct/double-count).
    AM + PM on the same day is legal; anything overlapping FULL is not.
    """
    for other in overlapping_requests(
        person_id, request.start_date, request.end_date, exclude_id=request.id
    ):
        if other.status is not RequestStatus.APPROVED:
            continue
        if (
            request.day_part is DayPart.FULL
            or other.day_part is DayPart.FULL
            or other.day_part is request.day_part
        ):
            return other
    return None


def deduction_half_days(request) -> int:
    """Half-days this request costs on approval. LL/OL and non-working days cost 0."""
    if request.type not in BALANCE_TRACKED:
        return 0
    holidays = PublicHoliday.dates_between(request.start_date, request.end_date)
    if request.day_part is not DayPart.FULL:
        return 1 if is_working_day(request.start_date, holidays) else 0
    return 2 * working_days(request.start_date, request.end_date, holidays)


def deduction_note(request) -> str:
    """Human-readable breakdown shown to requester and approvers."""
    cost = deduction_half_days(request)
    span = (request.end_date - request.start_date).days + 1
    if request.type not in BALANCE_TRACKED:
        return f"No balance deduction ({request.type.value} is recorded only)."
    if cost == 0:
        return "No working days in this range — nothing will be deducted."
    days = f"{cost / 2:g}"
    if span > 1:
        return f"{span} calendar days = {days} {request.type.value} deducted (working days only)."
    return f"{days} {request.type.value} deducted."
