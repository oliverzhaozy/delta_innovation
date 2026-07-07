"""TU manning pages (P6.4). Everything is S3/admin (`can_manage_manning`) —
manning is the S3's working tool, like meals, not broadcast information.
Views stay thin: manning_service owns candidates, transactions, and the
document build; routes translate typed exceptions to 4xx/flash.
"""
from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.authz import require
from app.blueprints.manning import bp
from app.domain import policy
from app.domain.types import ManningSlotType
from app.extensions import db
from app.models import ManningPeriod, Person
from app.services import manning_service


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
        name=request.form.get("name", "").strip() or None,
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
        next_det=(max(det_numbers) + 1) if det_numbers else 1,
        ManningSlotType=ManningSlotType,
    )


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
