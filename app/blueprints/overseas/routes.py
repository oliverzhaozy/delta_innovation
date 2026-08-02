from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.overseas import bp
from app.blueprints.overseas.forms import OverseasDeclarationForm
from app.domain import policy, routing
from app.domain.dates import today_sgt
from app.domain.types import DeclarationStatus
from app.extensions import db
from app.models import OverseasDeclaration, Person
from app.services import overseas_service
from app.services.approval_service import TransitionError


@bp.route("/declare", methods=["GET", "POST"])
@login_required
def declare():
    # Everyone declares — unlike leave, this isn't gated by routing.can_request
    # (TECH_PLAN RBAC line: "Everyone: ... declare overseas").
    form = OverseasDeclarationForm()
    if form.validate_on_submit():
        status = routing.overseas_initial_status(current_user.appointment)
        row = OverseasDeclaration(
            person_id=current_user.id,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            destination=form.destination.data.strip(),
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        if status is DeclarationStatus.PENDING:
            flash("Declared — pending PC approval.", "success")
        else:
            flash("Declared.", "success")
        return redirect(url_for("overseas.mine"))
    return render_template("overseas/declare.html", form=form)


@bp.route("/mine")
@login_required
def mine():
    overseas_service.purge_expired()
    declarations = (
        db.session.query(OverseasDeclaration)
        .filter_by(person_id=current_user.id)
        .order_by(OverseasDeclaration.created_at.desc())
        .all()
    )
    return render_template("overseas/mine.html", declarations=declarations)


@bp.route("/<int:declaration_id>/retract", methods=["POST"])
@login_required
def retract(declaration_id):
    row = db.session.get(OverseasDeclaration, declaration_id) or abort(404)
    if row.person_id != current_user.id:
        abort(403)
    # Retract deletes, whatever the status (owner directive 2026-07-28): no
    # travel history is kept, so there is nothing to mark cancelled.
    db.session.delete(row)
    db.session.commit()
    flash("Retracted.", "success")
    return redirect(url_for("overseas.mine"))


@bp.route("/upcoming")
@require(policy.can_manage_manning)
def upcoming():
    overseas_service.purge_expired()
    declarations = (
        db.session.query(OverseasDeclaration)
        .join(Person, OverseasDeclaration.person_id == Person.id)
        .filter(
            # Pending travel is still travel — the S3 plans around it and the
            # manning check flags it; only a rejected declaration is nothing.
            OverseasDeclaration.status != DeclarationStatus.REJECTED,
            OverseasDeclaration.end_date >= today_sgt(),
        )
        .order_by(OverseasDeclaration.start_date)
        .all()
    )
    return render_template("overseas/upcoming.html", declarations=declarations)


@bp.route("/queue")
@require(policy.can_approve_as_pc)
def queue():
    overseas_service.purge_expired()
    declarations = (
        db.session.query(OverseasDeclaration)
        .join(Person, OverseasDeclaration.person_id == Person.id)
        .filter(OverseasDeclaration.status == DeclarationStatus.PENDING)
        # Most upcoming travel first, matching the leave queues' ordering.
        .order_by(OverseasDeclaration.start_date)
        .all()
    )
    return render_template(
        "overseas/queue.html",
        declarations=declarations,
        on_manning=overseas_service.on_manning_ids(declarations),
    )


@bp.route("/<int:declaration_id>/approve", methods=["POST"])
@require(policy.can_approve_as_pc)
def approve(declaration_id):
    row = db.session.get(OverseasDeclaration, declaration_id) or abort(404)
    try:
        overseas_service.pc_approve(row, current_user)
        flash("Approved.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("overseas.queue"))


@bp.route("/<int:declaration_id>/reject", methods=["POST"])
@require(policy.can_approve_as_pc)
def reject(declaration_id):
    row = db.session.get(OverseasDeclaration, declaration_id) or abort(404)
    try:
        overseas_service.pc_reject(row, current_user)
        flash("Rejected.", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("overseas.queue"))
