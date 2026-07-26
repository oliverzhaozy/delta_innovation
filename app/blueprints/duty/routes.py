"""Duty roster page + mutations (P4.5/P4.6). Views are thin wires:
duty_service.month_view assembles everything the page renders; the service
functions own the transactions and raise typed exceptions these routes
translate to 4xx (rule violations) or flash-and-redirect (judgment warnings).
"""
from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.duty import bp
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.parade import parade_sort_key
from app.domain.types import Duty
from app.extensions import db
from app.models import Person
from app.services import duty_service


def _parse_month(raw: str) -> str:
    # Same posture the RO/meals date pages use: a bad ?month= falls back to the
    # current month rather than 400ing — the page must always render something.
    try:
        duty_service.month_bounds(raw)
        return raw
    except (ValueError, AttributeError):
        return today_sgt().strftime("%Y-%m")


def _flag_order(person, person_id):
    """Parade order for one adjacency flag's holder. A holder outside this
    month's pools (a prior-month tail row, or someone since deactivated) has no
    parade key at all — they sort after the roster, by id, rather than ahead of
    it on an empty key.
    """
    if person is None:
        return (1, (person_id,))
    return (0, parade_sort_key(person))


@bp.route("/roster")
@login_required
def roster():
    month = _parse_month(request.args.get("month", ""))
    view = duty_service.month_view(month)
    people_by_id = {p.id: p for duty in Duty for p in view.pools[duty]}
    adjacency_marks = {
        (person_id, d) for person_id, d1, d2 in view.violations.adjacency for d in (d1, d2)
    }
    # roster.violations is pure and carries person IDS, so the parade order of
    # its flag lines is applied HERE, where the page already holds the people.
    adjacency_rows = sorted(
        view.violations.adjacency,
        key=lambda flag: (_flag_order(people_by_id.get(flag[0]), flag[0]), flag[1], flag[2]),
    )
    return render_template(
        "duty/roster.html",
        month=month,
        view=view,
        Duty=Duty,
        roster_people=sorted(people_by_id.values(), key=parade_sort_key),
        people_by_id=people_by_id,
        adjacency_marks=adjacency_marks,
        adjacency_rows=adjacency_rows,
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


@bp.route("/roster/assign", methods=["POST"])
@require(policy.can_manage_roster)
def assign():
    month = _parse_month(request.form.get("month", ""))
    try:
        day = date.fromisoformat(request.form.get("date", ""))
        duty = Duty(request.form.get("duty", ""))
        person = db.session.get(Person, int(request.form.get("person_id", "")))
    except (ValueError, TypeError):
        abort(400)
    if person is None:
        abort(400)
    try:
        duty_service.assign(
            day, duty, person, actor=current_user,
            override_availability=request.form.get("confirm") == "1",
        )
    except duty_service.IneligibleAssignment as exc:
        abort(400, description=str(exc))
    except duty_service.NeedsAvailabilityConfirm as exc:
        flash(f"Not assigned — {exc}. Tick “assign anyway” to override.", "error")
        return redirect(url_for("duty.roster", month=month))
    flash("Assigned.", "success")
    return redirect(url_for("duty.roster", month=month))


@bp.route("/roster/clear", methods=["POST"])
@require(policy.can_manage_roster)
def clear():
    month = _parse_month(request.form.get("month", ""))
    try:
        day = date.fromisoformat(request.form.get("date", ""))
        duty = Duty(request.form.get("duty", ""))
    except ValueError:
        abort(400)
    flash("Cleared." if duty_service.clear(day, duty) else "Nothing to clear.", "success")
    return redirect(url_for("duty.roster", month=month))
