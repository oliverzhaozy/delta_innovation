"""Duty roster page + mutations (P4.5/P4.6). Views are thin wires:
duty_service.month_view assembles everything the page renders; the service
functions own the transactions and raise typed exceptions these routes
translate to 4xx (rule violations) or flash-and-redirect (judgment warnings).
"""
from datetime import timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.authz import require
from app.blueprints.duty import bp
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import Duty
from app.extensions import db
from app.models import DutySwapLog
from app.services import duty_service


def _parse_month(raw: str) -> str:
    # Same posture as parade's _parse_day: a bad ?month= falls back to the
    # current month rather than 400ing — the page must always render something.
    try:
        duty_service.month_bounds(raw)
        return raw
    except (ValueError, AttributeError):
        return today_sgt().strftime("%Y-%m")


@bp.route("/roster")
@login_required
def roster():
    month = _parse_month(request.args.get("month", ""))
    view = duty_service.month_view(month)
    swap_log = (
        db.session.query(DutySwapLog)
        .options(
            joinedload(DutySwapLog.person_a),
            joinedload(DutySwapLog.person_b),
            joinedload(DutySwapLog.actor),
        )
        .order_by(DutySwapLog.at.desc(), DutySwapLog.id.desc())
        .all()
    )
    people_by_id = {p.id: p for duty in Duty for p in view.pools[duty]}
    adjacency_marks = {
        (person_id, d) for person_id, d1, d2 in view.violations.adjacency for d in (d1, d2)
    }
    return render_template(
        "duty/roster.html",
        month=month,
        view=view,
        Duty=Duty,
        swap_log=swap_log,
        roster_people=sorted(people_by_id.values(), key=lambda p: p.display_name),
        people_by_id=people_by_id,
        adjacency_marks=adjacency_marks,
        prev_month=(view.first - timedelta(days=1)).strftime("%Y-%m"),
        next_month=(view.last + timedelta(days=1)).strftime("%Y-%m"),
    )


@bp.route("/roster/generate", methods=["POST"])
@require(policy.can_manage_roster)
def generate():
    month = _parse_month(request.form.get("month", ""))
    duty_service.generate_month(month, current_user)
    flash("Draft roster generated — review, then confirm.", "success")
    return redirect(url_for("duty.roster", month=month))


@bp.route("/roster/confirm", methods=["POST"])
@require(policy.can_manage_roster)
def confirm():
    month = _parse_month(request.form.get("month", ""))
    try:
        duty_service.confirm_month(month, current_user, request.form.get("fingerprint", ""))
    except duty_service.RosterChanged as exc:
        flash(str(exc), "error")
    else:
        flash("Month confirmed — parades and meals now read these duties.", "success")
    return redirect(url_for("duty.roster", month=month))
