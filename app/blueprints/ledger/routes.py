from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from app.authz import require
from app.blueprints.ledger import bp
from app.blueprints.ledger.forms import AdjustmentForm
from app.domain import policy
from app.domain.types import BalanceKind, LedgerSource
from app.extensions import db
from app.models import Person
from app.services import event_service, ledger_service


@bp.route("/")
@require(policy.can_manage_ledger)
def index():
    # The shared active-roster fetch, so this table reads the same people in the
    # same parade order (appointment → rank) as every other list in the app.
    people = event_service.active_roster()
    return render_template(
        "ledger/index.html", people=people, all_balances=ledger_service.balances_for_everyone()
    )


@bp.route("/person/<int:person_id>")
@require(policy.can_manage_ledger)
def person(person_id):
    person_row = db.session.get(Person, person_id) or abort(404)
    return render_template(
        "ledger/person.html",
        person=person_row,
        balances=ledger_service.balances(person_id),
        entries=ledger_service.history(person_id),
    )


@bp.route("/person/<int:person_id>/adjust", methods=["GET", "POST"])
@require(policy.can_manage_ledger)
def adjust(person_id):
    person_row = db.session.get(Person, person_id) or abort(404)
    form = AdjustmentForm()
    if form.validate_on_submit():
        half_days = int(form.days.data * 2)
        if form.direction.data == "deduct":
            half_days = -half_days
        ledger_service.post_entry(
            person_id=person_row.id,
            kind=BalanceKind(form.kind.data),
            delta_half_days=half_days,
            reason=form.reason.data.strip(),
            source=LedgerSource.MANUAL,
            created_by_id=current_user.id,
        )
        db.session.commit()
        flash("Adjustment recorded.", "success")
        return redirect(url_for("ledger.person", person_id=person_row.id))
    return render_template("ledger/adjust.html", person=person_row, form=form)
