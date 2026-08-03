"""TU manning pages (P6.4). Building is S3/admin (`can_manage_manning`) —
manning is the S3's working tool, like meals, not broadcast information — and
the approval half (decision (ff)) is PC-only, the same split the overseas
blueprint uses. Views stay thin: manning_service owns candidates, transactions,
and the document build; routes translate typed exceptions to 4xx/flash.
"""
from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.authz import require
from app.blueprints.manning import bp
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import ManningSlotType
from app.extensions import db
from app.models import ManningPeriod, Person
from app.services import manning_service
from app.services.approval_service import TransitionError


def _get_period(period_id):
    return db.session.get(ManningPeriod, period_id) or abort(404)


def _parse_date(raw):
    try:
        return date.fromisoformat(raw)
    except ValueError:
        abort(400)


@bp.route("")
@require(policy.can_manage_manning)
def index():
    periods = (
        db.session.query(ManningPeriod)
        .order_by(ManningPeriod.start_date.desc(), ManningPeriod.id.desc())
        .all()
    )
    return render_template("manning/index.html", periods=periods)


@bp.route("/new", methods=["POST"])
@require(policy.can_manage_manning)
def new():
    start = _parse_date(request.form.get("start_date", ""))
    end = _parse_date(request.form.get("end_date", ""))
    if end < start:
        flash("End date is before start date.", "error")
        return redirect(url_for("manning.index"))
    period = ManningPeriod(
        start_date=start, end_date=end, created_by_id=current_user.id,
    )
    db.session.add(period)
    db.session.commit()
    flash("Period created.", "success")
    return redirect(url_for("manning.builder", period_id=period.id))


@bp.route("/<int:period_id>")
@require(policy.can_manage_manning)
def builder(period_id):
    period = _get_period(period_id)
    doc = manning_service.build_document(period)
    candidates = manning_service.candidates(period)
    checks = manning_service.conflict_map(period)
    # One last-done fetch feeds both the priority card and the dropdown
    # suffixes; the reference date is passed in, never read inside the ranking.
    last_done = manning_service.last_manning_end()
    hq = [s for s in period.slots if s.det_number is None]
    det_numbers = sorted({s.det_number for s in period.slots if s.det_number is not None})
    dets = {
        det: sorted(
            (s for s in period.slots if s.det_number == det),
            # DET COMD line first, mirroring the document.
            key=lambda s: s.slot is not ManningSlotType.TU_DET_COMD,
        )
        for det in det_numbers
    }
    return render_template(
        "manning/builder.html",
        period=period,
        doc=doc,
        candidates=candidates,
        checks=checks,
        hq=hq,
        dets=dets,
        open_positions=manning_service.open_positions(period),
        priority=manning_service.slot_priority(last_done),
        last_done=last_done,
        today=today_sgt(),
        ManningSlotType=ManningSlotType,
    )


@bp.route("/<int:period_id>/generate", methods=["POST"])
@require(policy.can_manage_manning)
def generate(period_id):
    period = _get_period(period_id)
    filled, open_before = manning_service.generate_period(period)
    flash(
        f"Generated {filled} of {open_before} open slots (keeps manual picks).",
        "success",
    )
    return redirect(url_for("manning.builder", period_id=period.id))


@bp.route("/<int:period_id>/assign", methods=["POST"])
@require(policy.can_manage_manning)
def assign(period_id):
    period = _get_period(period_id)
    try:
        slot = ManningSlotType(request.form.get("slot", ""))
        person = db.session.get(Person, int(request.form.get("person_id", "")))
    except ValueError:
        abort(400)
    if person is None:
        abort(400)
    raw_det = request.form.get("det_number", "").strip()
    det_number = None
    if slot in (ManningSlotType.TU_DET_COMD, ManningSlotType.DET_PERSONNEL):
        try:
            det_number = int(raw_det)
        except ValueError:
            flash("Det slots need a det number.", "error")
            return redirect(url_for("manning.builder", period_id=period.id))
    try:
        manning_service.assign_slot(period, slot, person, det_number=det_number)
    except manning_service.IneligibleSlot as exc:
        abort(400, description=str(exc))
    except manning_service.DuplicatePerson as exc:
        flash(str(exc), "error")
        return redirect(url_for("manning.builder", period_id=period.id))
    flash("Assigned.", "success")
    return redirect(url_for("manning.builder", period_id=period.id))


@bp.route("/<int:period_id>/reassign", methods=["POST"])
@require(policy.can_manage_manning)
def reassign(period_id):
    period = _get_period(period_id)
    try:
        slot_id = int(request.form.get("slot_id", ""))
        person = db.session.get(Person, int(request.form.get("person_id", "")))
    except ValueError:
        abort(400)
    if person is None:
        abort(400)
    try:
        row = manning_service.reassign_slot(period, slot_id, person)
    except manning_service.IneligibleSlot as exc:
        abort(400, description=str(exc))
    except manning_service.DuplicatePerson as exc:
        flash(str(exc), "error")
        return redirect(url_for("manning.builder", period_id=period.id))
    if row is None:
        abort(404)
    flash("Reassigned.", "success")
    return redirect(url_for("manning.builder", period_id=period.id))


@bp.route("/<int:period_id>/remove", methods=["POST"])
@require(policy.can_manage_manning)
def remove(period_id):
    period = _get_period(period_id)
    try:
        slot_id = int(request.form.get("slot_id", ""))
    except ValueError:
        abort(400)
    flash(
        "Removed." if manning_service.remove_slot(slot_id) else "Nothing to remove.",
        "success",
    )
    return redirect(url_for("manning.builder", period_id=period.id))


@bp.route("/<int:period_id>/delete", methods=["POST"])
@require(policy.can_manage_manning)
def delete(period_id):
    period = _get_period(period_id)
    db.session.delete(period)
    db.session.commit()
    flash("Period deleted.", "success")
    return redirect(url_for("manning.index"))


# --- approval: the S3 hands over, a PC decides (decision (ff)) -----------------------

@bp.route("/<int:period_id>/confirm", methods=["POST"])
@require(policy.can_manage_manning)
def confirm(period_id):
    period = _get_period(period_id)
    try:
        manning_service.confirm_period(period, current_user)
        flash("Sent for PC approval.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("manning.builder", period_id=period.id))


@bp.route("/<int:period_id>/withdraw", methods=["POST"])
@require(policy.can_manage_manning)
def withdraw(period_id):
    period = _get_period(period_id)
    try:
        manning_service.withdraw_period(period, current_user)
        flash("Withdrawn — back to draft.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("manning.builder", period_id=period.id))


@bp.route("/queue")
@require(policy.can_approve_as_pc)
def queue():
    # Each period is rendered inline: 0–1 are pending at a time, so a separate
    # detail page would be a click for nothing. The PC reads the SAME document
    # build_document gives the S3 — there is no second rendering.
    periods = manning_service.pending_periods()
    return render_template(
        "manning/queue.html",
        periods=periods,
        documents={p.id: manning_service.build_document(p) for p in periods},
    )


@bp.route("/<int:period_id>/approve", methods=["POST"])
@require(policy.can_approve_as_pc)
def approve(period_id):
    period = _get_period(period_id)
    try:
        manning_service.pc_approve_period(period, current_user)
        flash("Approved.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("manning.queue"))


@bp.route("/<int:period_id>/reject", methods=["POST"])
@require(policy.can_approve_as_pc)
def reject(period_id):
    period = _get_period(period_id)
    remark = (request.form.get("remarks") or "").strip()
    if not remark:
        flash("A short remark is required when rejecting.", "error")
        return redirect(url_for("manning.queue"))
    try:
        manning_service.pc_reject_period(period, current_user, remark)
        flash("Sent back to the S3.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("manning.queue"))
