from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.overseas import bp
from app.blueprints.overseas.forms import OverseasDeclarationForm
from app.domain import policy
from app.domain.dates import now_sgt, today_sgt
from app.extensions import db
from app.models import OverseasDeclaration, Person


@bp.route("/declare", methods=["GET", "POST"])
@login_required
def declare():
    # Everyone declares — unlike leave, this isn't gated by routing.can_request
    # (TECH_PLAN RBAC line: "Everyone: ... declare overseas").
    form = OverseasDeclarationForm()
    if form.validate_on_submit():
        row = OverseasDeclaration(
            person_id=current_user.id,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            destination=form.destination.data.strip(),
        )
        db.session.add(row)
        db.session.commit()
        flash("Declared.", "success")
        return redirect(url_for("overseas.mine"))
    return render_template("overseas/declare.html", form=form)


@bp.route("/mine")
@login_required
def mine():
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
    if row.cancelled_at is None:
        row.cancelled_at = now_sgt()
        db.session.commit()
        flash("Retracted.", "success")
    else:
        flash("Already retracted.", "error")
    return redirect(url_for("overseas.mine"))


@bp.route("/upcoming")
@require(policy.can_manage_manning)
def upcoming():
    declarations = (
        db.session.query(OverseasDeclaration)
        .join(Person, OverseasDeclaration.person_id == Person.id)
        .filter(
            OverseasDeclaration.cancelled_at.is_(None),
            OverseasDeclaration.end_date >= today_sgt(),
        )
        .order_by(OverseasDeclaration.start_date)
        .all()
    )
    return render_template("overseas/upcoming.html", declarations=declarations)
