"""Duty roster page + mutations (P4.5/P4.6). Views are thin wires:
duty_service.month_view assembles everything the page renders; the service
functions own the transactions and raise typed exceptions these routes
translate to 4xx (rule violations) or a re-rendered page / flash-and-redirect
(judgment warnings).
"""
from collections import namedtuple
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

PendingAssign = namedtuple("PendingAssign", "day duty person reasons")


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
    month's pools (a prior-month tail row, or someone since deleted) has no
    parade key at all — they sort after the roster, by id, rather than ahead of
    it on an empty key.
    """
    if person is None:
        return (1, (person_id,))
    return (0, parade_sort_key(person))


def _render_roster(month, *, pending_assign=None):
    """The roster page, from the GET and from an assign that hit a warning —
    one builder, so the conflict card renders over the very page the user was
    looking at."""
    # The priority chips date FROM today: the reference date is passed into the
    # template, never read inside a domain function.
    today = today_sgt()
    view = duty_service.month_view(month)
    # The per-cell dropdowns read the UNFILTERED pools (view.assignable_priority):
    # a platoon excused the COS pool is warned about on assign, not hidden
    # (decision (ee)). Name lookup adds the current holders on top — an excused
    # (or since-exempted) person can hold a slot, and a flag line must name them
    # rather than print a bare id.
    people_by_id = {p.id: p for duty in Duty for p in view.assignable_pools[duty]}
    people_by_id.update({row.person_id: row.person for row in view.rows})
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
        people_by_id=people_by_id,
        adjacency_marks=adjacency_marks,
        adjacency_rows=adjacency_rows,
        pending_assign=pending_assign,
        prev_month=(view.first - timedelta(days=1)).strftime("%Y-%m"),
        next_month=(view.last + timedelta(days=1)).strftime("%Y-%m"),
        today=today,
        today_month=today.strftime("%Y-%m"),
    )


@bp.route("/roster")
@login_required
def roster():
    return _render_roster(_parse_month(request.args.get("month", "")))


@bp.route("/roster/generate", methods=["POST"])
@require(policy.can_manage_roster)
def generate():
    month = _parse_month(request.form.get("month", ""))
    duty_service.generate_month(month, current_user)
    flash("Roster generated.", "success")
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
        # The override decision belongs AFTER the user knows the conflict, so
        # the warning re-renders the page with a confirm card instead of
        # redirecting to a flash.
        return _render_roster(
            month,
            pending_assign=PendingAssign(
                day=day, duty=duty, person=person, reasons=exc.reasons
            ),
        )
    flash("Assigned.", "success")
    return redirect(url_for("duty.roster", month=month))


@bp.route("/roster/block", methods=["POST"])
@require(policy.can_manage_roster)
def block():
    month = _parse_month(request.form.get("month", ""))
    try:
        day = date.fromisoformat(request.form.get("date", ""))
    except ValueError:
        abort(400)
    try:
        removed = duty_service.block_day(day, current_user)
    except duty_service.NotBlockable as exc:
        flash(str(exc), "error")
    else:
        tail = f" — removed {', '.join(removed)}." if removed else "."
        flash(f"Blocked {day.strftime('%d/%m')}{tail}", "success")
    return redirect(url_for("duty.roster", month=month))


@bp.route("/roster/unblock", methods=["POST"])
@require(policy.can_manage_roster)
def unblock():
    month = _parse_month(request.form.get("month", ""))
    try:
        day = date.fromisoformat(request.form.get("date", ""))
    except ValueError:
        abort(400)
    if duty_service.unblock_day(day):
        flash(f"Unblocked {day.strftime('%d/%m')}.", "success")
    else:
        flash(f"{day.strftime('%d/%m')} was not blocked.", "error")
    return redirect(url_for("duty.roster", month=month))
