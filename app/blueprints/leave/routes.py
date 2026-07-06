from flask import abort, flash, redirect, render_template, request as http_request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.leave import bp
from app.blueprints.leave.forms import LeaveRequestForm
from app.domain import policy, routing
from app.domain.dates import iter_days
from app.domain.types import (
    BalanceKind,
    DayPart,
    LeaveType,
    PENDING_STATUSES,
    RequestStatus,
)
from app.extensions import db
from app.models import LeaveRequest, Person
from app.services import approval_service, event_service, leave_service, ledger_service, presence_service
from app.services.approval_service import NegativeBalanceUnconfirmed, TransitionError


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
        # Informational only — clash info never blocks or reroutes a request
        # (CLAUDE.md: the app proposes, a human decides).
        clashes = event_service.clashes_for(
            request_row, include_arctic=policy.can_view_arctic(current_user)
        )
        if clashes:
            titles = ", ".join(c.title for c in clashes)
            flash(
                f"You're tagged in {len(clashes)} conduct(s) on those dates: {titles}.",
                "warning",
            )
        return redirect(url_for("leave.index"))
    return render_template(
        "leave/new.html",
        form=form,
        balances=ledger_service.balances(current_user.id),
    )


def _may_view(request_row):
    return (
        request_row.person_id == current_user.id
        or policy.can_final_approve(current_user)
        or policy.can_manage_ledger(current_user)
        or (
            policy.is_pc(current_user)
            and request_row.person.platoon is not None
            and request_row.person.platoon == current_user.platoon
        )
    )


@bp.route("/queue/pc")
@require(policy.is_pc)
def pc_queue():
    pending = (
        db.session.query(LeaveRequest)
        .join(Person, LeaveRequest.person_id == Person.id)
        .filter(
            LeaveRequest.status == RequestStatus.PENDING_PC,
            Person.platoon == current_user.platoon,
        )
        .order_by(LeaveRequest.created_at)
        .all()
    )
    return render_template(
        "leave/queue.html", pending=pending, title=f"Platoon {current_user.platoon} approvals"
    )


@bp.route("/queue/oc")
@require(policy.can_final_approve)
def oc_queue():
    pending = (
        db.session.query(LeaveRequest)
        .filter(LeaveRequest.status == RequestStatus.PENDING_OC)
        .order_by(LeaveRequest.created_at)
        .all()
    )
    return render_template("leave/queue.html", pending=pending, title="Final approvals")


@bp.route("/<int:request_id>")
@login_required
def detail(request_id):
    request_row = db.session.get(LeaveRequest, request_id) or abort(404)
    if not _may_view(request_row):
        abort(403)
    cost = leave_service.deduction_half_days(request_row)
    balances = ledger_service.balances(request_row.person_id)
    projected = None
    if request_row.type.value in BalanceKind.__members__ and cost:
        projected = balances[BalanceKind(request_row.type.value)] - cost
    overlaps = leave_service.overlapping_requests(
        request_row.person_id,
        request_row.start_date,
        request_row.end_date,
        exclude_id=request_row.id,
    )
    # Same viewer rule for everyone on this page (requester, PC, OC, S3):
    # ARCTIC rows only surface for ARCTIC-cleared viewers.
    clashes = event_service.clashes_for(
        request_row, include_arctic=policy.can_view_arctic(current_user)
    )
    away_counts = presence_service.absences_between(request_row.start_date, request_row.end_date)
    away_rows = [
        {
            "day": d,
            # Distinct people, not rows — matches the P2.6 month cell's dedupe
            # so the two surfaces never disagree on who's away.
            "count": len({r.person_id for r in away_counts.get(d, [])}),
        }
        for d in iter_days(request_row.start_date, request_row.end_date)
    ]
    can_act_pc = (
        request_row.status is RequestStatus.PENDING_PC
        and policy.can_approve_as_pc(current_user, request_row.person.platoon)
        and request_row.person_id != current_user.id
    )
    can_act_oc = (
        request_row.status is RequestStatus.PENDING_OC
        and policy.can_final_approve(current_user)
        and request_row.person_id != current_user.id
    )
    return render_template(
        "leave/detail.html",
        r=request_row,
        balances=balances,
        deduction_note=leave_service.deduction_note(request_row),
        projected=projected,
        overlaps=overlaps,
        clashes=clashes,
        away_rows=away_rows,
        can_act_pc=can_act_pc,
        can_act_oc=can_act_oc,
    )


def _act(request_id, expected_status, platoon_scoped):
    """Shared guard for the four action endpoints; returns the request row."""
    request_row = db.session.get(LeaveRequest, request_id) or abort(404)
    if platoon_scoped and not policy.can_approve_as_pc(current_user, request_row.person.platoon):
        abort(403)
    return request_row


@bp.route("/<int:request_id>/pc-approve", methods=["POST"])
@require(policy.is_pc)
def pc_approve(request_id):
    request_row = _act(request_id, RequestStatus.PENDING_PC, platoon_scoped=True)
    try:
        approval_service.pc_approve(request_row, current_user)
        flash("Endorsed — now with the OC.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("leave.detail", request_id=request_id))


@bp.route("/<int:request_id>/pc-reject", methods=["POST"])
@require(policy.is_pc)
def pc_reject(request_id):
    request_row = _act(request_id, RequestStatus.PENDING_PC, platoon_scoped=True)
    remark = (http_request.form.get("remark") or "").strip()
    if not remark:
        flash("A short remark is required when rejecting.", "error")
        return redirect(url_for("leave.detail", request_id=request_id))
    try:
        approval_service.pc_reject(request_row, current_user, remark)
        flash("Rejected.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("leave.detail", request_id=request_id))


@bp.route("/<int:request_id>/oc-approve", methods=["POST"])
@require(policy.can_final_approve)
def oc_approve(request_id):
    request_row = _act(request_id, RequestStatus.PENDING_OC, platoon_scoped=False)
    confirm_negative = http_request.form.get("confirm_negative") == "1"
    try:
        approval_service.oc_approve(request_row, current_user, confirm_negative=confirm_negative)
        flash("Approved — plotted and deducted in one step.", "success")
    except NegativeBalanceUnconfirmed as exc:
        flash(
            f"This would take the balance to {exc.projected_half_days / 2:g}. "
            "Tick 'approve anyway' to confirm a negative balance.",
            "warning",
        )
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("leave.detail", request_id=request_id))


@bp.route("/<int:request_id>/oc-reject", methods=["POST"])
@require(policy.can_final_approve)
def oc_reject(request_id):
    request_row = _act(request_id, RequestStatus.PENDING_OC, platoon_scoped=False)
    remark = (http_request.form.get("remark") or "").strip()
    if not remark:
        flash("A short remark is required when rejecting.", "error")
        return redirect(url_for("leave.detail", request_id=request_id))
    try:
        approval_service.oc_reject(request_row, current_user, remark)
        flash("Rejected.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("leave.detail", request_id=request_id))


@bp.route("/<int:request_id>/cancel-approved", methods=["POST"])
@require(policy.can_cancel_approved_leave)
def cancel_approved(request_id):
    request_row = db.session.get(LeaveRequest, request_id) or abort(404)
    try:
        approval_service.cancel_approved(request_row, current_user)
        flash("Cancelled — the deduction was reversed and the absence unplotted.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("leave.detail", request_id=request_id))


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
