from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from app.authz import require
from app.blueprints.ledger import bp
from app.blueprints.ledger.forms import BULK_AWARD_CATEGORIES, AdjustmentForm, BulkAwardForm
from app.domain import parade, participants, policy
from app.domain.types import BalanceKind, LedgerSource, ParticipantCategory, Service
from app.extensions import db
from app.models import Person
from app.services import event_service, ledger_service


@bp.route("/")
@require(policy.can_manage_ledger)
def index():
    # The shared active-roster fetch, so this table reads the same people in the
    # same parade order (appointment → rank) as every other list in the app.
    # NSFs only: regulars' off/leave lives in ARCTIC FOE (owner directive
    # 2026-07-26), so they have no balances here.
    people = [p for p in event_service.active_roster() if p.service is Service.NSF]
    return render_template(
        "ledger/index.html", people=people, all_balances=ledger_service.balances_for_everyone()
    )


@bp.route("/bulk-award", methods=["GET", "POST"])
@require(policy.can_manage_ledger)
def bulk_award():
    # NSFs only: regulars' off/leave lives in ARCTIC FOE (owner directive
    # 2026-07-26), so the picker never lists them and every category resolves
    # against the NSF-only active roster (same rule as the ledger index).
    roster = [p for p in event_service.active_roster() if p.service is Service.NSF]
    form = BulkAwardForm()
    form.people.choices = [(p.id, f"{p.rank.value} {p.display_name}") for p in roster]
    if form.validate_on_submit():
        # Categories expand to concrete NSF ids NOW (nothing category-shaped is
        # stored — each award is a per-person ledger line). Ticked ids are
        # intersected with the NSF roster as a belt-and-braces object check on
        # top of the form's choice validation.
        values = set(form.categories.data)
        selected = set(form.people.data) & {p.id for p in roster}
        selected.update(
            p.id
            for p in roster
            if any(participants.in_category(p, ParticipantCategory(v)) for v in values)
        )
        if not selected:
            flash("Select at least one person or group.", "error")
        else:
            kind = BalanceKind(form.kind.data)
            half_days = int(form.days.data * 2)
            reason = form.reason.data.strip()
            for person_id in sorted(selected):
                ledger_service.post_entry(
                    person_id=person_id,
                    kind=kind,
                    delta_half_days=half_days,
                    reason=reason,
                    source=LedgerSource.MANUAL,
                    created_by_id=current_user.id,
                )
            db.session.commit()  # the whole batch lands or fails as one transaction
            flash(f"Awarded {form.days.data} {kind.value} to {len(selected)} people.", "success")
            return redirect(url_for("ledger.index"))
    picker_groups = [
        (
            category,
            sorted(
                (p for p in roster if participants.in_category(p, category)),
                key=parade.parade_sort_key,
            ),
        )
        for category in BULK_AWARD_CATEGORIES
    ]
    # The picker's Command team row is hidden here (picker_hide_top), so no id
    # needs a data-command marker; the include still evaluates `p.id in
    # command_ids`, so pass an empty set to keep that reference safe.
    return render_template(
        "ledger/bulk_award.html", form=form, picker_groups=picker_groups, command_ids=set()
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
