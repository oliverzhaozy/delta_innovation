from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.blueprints.leave import bp
from app.blueprints.leave.forms import LeaveRequestForm
from app.domain import routing
from app.domain.types import (
    BalanceKind,
    DayPart,
    LeaveType,
    PENDING_STATUSES,
    RequestStatus,
)
from app.extensions import db
from app.models import LeaveRequest
from app.services import leave_service, ledger_service


def _require_requester():
    if not routing.can_request(current_user):
        # Regulars are outside the request flow; S3 records their absences.
        abort(403)


@bp.route("/")
@login_required
def index():
    _require_requester()
    requests = (
        db.session.query(LeaveRequest)
        .filter_by(person_id=current_user.id)
        .order_by(LeaveRequest.created_at.desc())
        .all()
    )
    return render_template(
        "leave/index.html",
        requests=requests,
        balances=ledger_service.balances(current_user.id),
        deduction_note=leave_service.deduction_note,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    _require_requester()
    form = LeaveRequestForm()
    if form.validate_on_submit():
        request_row = LeaveRequest(
            person_id=current_user.id,
            type=LeaveType(form.type.data),
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            day_part=DayPart(form.day_part.data),
            reason=(form.reason.data or "").strip() or None,
            status=routing.initial_status(current_user.appointment),
        )
        overlaps = leave_service.overlapping_requests(
            current_user.id, request_row.start_date, request_row.end_date
        )
        db.session.add(request_row)
        db.session.commit()
        if overlaps:
            flash(
                "Submitted — note it overlaps your existing request "
                f"({overlaps[0].when_label}, {overlaps[0].status.label}). "
                "Approvers will see this too.",
                "warning",
            )
        else:
            flash("Request submitted.", "success")
        return redirect(url_for("leave.index"))
    return render_template(
        "leave/new.html",
        form=form,
        balances=ledger_service.balances(current_user.id),
    )


@bp.route("/<int:request_id>/cancel", methods=["POST"])
@login_required
def cancel(request_id):
    request_row = db.session.get(LeaveRequest, request_id) or abort(404)
    if request_row.person_id != current_user.id:
        abort(403)
    if request_row.status not in PENDING_STATUSES:
        # Cancelling APPROVED leave reverses the ledger — that flow is S3/OC's
        # (see cancel_approved), not the requester's.
        flash("Only pending requests can be cancelled here — ask S3 to cancel approved leave.", "error")
        return redirect(url_for("leave.index"))
    request_row.status = RequestStatus.CANCELLED
    db.session.commit()
    flash("Request cancelled.", "success")
    return redirect(url_for("leave.index"))
