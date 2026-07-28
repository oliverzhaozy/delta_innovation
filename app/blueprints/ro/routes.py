"""RO pages (P5.5). The view is thin: ro_service.build assembles the whole
document; these routes translate forms into service calls and rights checks.
Daily edits are gated by can_edit_ro_for (decision (p): wide — any command
team member); the boilerplate surface is S3/admin staff work. Timeline
standing items and hand-keyed weekly key events were removed 2026-07-24 —
key events derive from the TP calendar.
"""
from datetime import date, time

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.ro import bp
from app.domain import policy
from app.domain.dates import next_weekday, prev_weekday, today_sgt
from app.domain.types import RoSection
from app.extensions import db
from app.models import RoBoilerplate
from app.services import ro_service


def _parse_day(raw: str) -> date:
    # The RO exists for weekdays only (owner 2026-07-28) and is compiled the
    # evening before, so the page defaults to the NEXT WEEKDAY — tomorrow, or
    # Monday across a weekend. A weekend URL rolls forward to that Monday rather
    # than 404ing: same never-400 posture as the parade pages. Every RO route
    # parses through here, so weekend RO documents can no longer be created.
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return next_weekday(today_sgt())
    if day.weekday() >= 5:
        return next_weekday(day)
    return day


def _parse_time(raw: str):
    """'HH:MM' from <input type=time>, or empty -> None (the TBC block)."""
    if not raw:
        return None
    try:
        return time.fromisoformat(raw)
    except ValueError:
        abort(400)


def _require_daily_editor(day):
    if not ro_service.can_edit_ro_for(current_user, day):
        abort(403)


@bp.route("")
@login_required
def view():
    day = _parse_day(request.args.get("date", ""))
    built = ro_service.build(day)
    doc = ro_service.fetch_or_create(day)
    return render_template(
        "ro/view.html",
        day=day,
        prev_day=prev_weekday(day),
        next_day=next_weekday(day),
        home_day=next_weekday(today_sgt()),
        built=built,
        doc=doc,
        can_edit=ro_service.can_edit_ro_for(current_user, day),
    )


@bp.route("/messages", methods=["POST"])
@login_required
def messages():
    day = _parse_day(request.form.get("date", ""))
    _require_daily_editor(day)
    ro_service.set_messages(ro_service.fetch_or_create(day), request.form.get("messages", ""))
    flash("Messages updated.", "success")
    return redirect(url_for("ro.view", date=day.isoformat()))


@bp.route("/extra/add", methods=["POST"])
@login_required
def extra_add():
    day = _parse_day(request.form.get("date", ""))
    _require_daily_editor(day)
    text = request.form.get("text", "").strip()
    if not text:
        flash("Timeline item needs text.", "error")
        return redirect(url_for("ro.view", date=day.isoformat()))
    ro_service.add_extra_item(
        ro_service.fetch_or_create(day),
        time_=_parse_time(request.form.get("time", "")),
        text=text,
    )
    flash("Timeline item added.", "success")
    return redirect(url_for("ro.view", date=day.isoformat()))


@bp.route("/extra/remove", methods=["POST"])
@login_required
def extra_remove():
    day = _parse_day(request.form.get("date", ""))
    _require_daily_editor(day)
    try:
        item_id = int(request.form.get("item_id", ""))
    except ValueError:
        abort(400)
    flash(
        "Timeline item removed." if ro_service.remove_extra_item(item_id)
        else "Nothing to remove.",
        "success",
    )
    return redirect(url_for("ro.view", date=day.isoformat()))


@bp.route("/boilerplate", methods=["GET", "POST"])
@require(policy.can_manage_ro_standing)
def boilerplate():
    if request.method == "POST":
        try:
            section = RoSection(request.form.get("section", ""))
        except ValueError:
            abort(400)
        ro_service.set_boilerplate(section, request.form.get("content", ""))
        flash(f"{section.label} updated.", "success")
        return redirect(url_for("ro.boilerplate"))
    rows = {row.section: row for row in db.session.query(RoBoilerplate).all()}
    return render_template("ro/boilerplate.html", sections=list(RoSection), rows=rows)
