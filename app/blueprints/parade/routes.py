from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.parade import bp
from app.blueprints.parade.forms import DirectAbsenceForm, StatusEntryForm
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import DayPart, DirectAbsenceType, STATUS_IN_CAMP_DEFAULT, Service, StatusType
from app.extensions import db
from app.models import DirectAbsence, Person, StatusEntry
from app.services import event_service, presence_service


@bp.route("/away")
@login_required
def away():
    raw = request.args.get("date", "")
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        day = today_sgt()
    summary = presence_service.away_summary(day)
    return render_template(
        "parade/away.html",
        day=day,
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        summary=summary,
        text=presence_service.away_text(day, summary),
    )


# --- Statuses (MC/course/briefing/site-testing/other) -----------------------

def _set_status_person_choices(form):
    # Request-time roster, not class-level, same reasoning as calendar's
    # _set_people_choices — who's active changes day to day.
    form.person_id.choices = [
        (p.id, f"{p.rank.value} {p.display_name}") for p in event_service.active_roster()
    ]


def _resolve_in_camp(type_value, in_camp_choice):
    if in_camp_choice == "IN":
        return True
    if in_camp_choice == "OUT":
        return False
    return STATUS_IN_CAMP_DEFAULT[StatusType(type_value)]  # DEFAULT


@bp.route("/statuses")
@require(policy.can_key_parade)
def statuses_list():
    today = today_sgt()
    rows = (
        db.session.query(StatusEntry)
        .join(Person, StatusEntry.person_id == Person.id)
        .filter(StatusEntry.end_date >= today)
        .order_by(StatusEntry.start_date)
        .all()
    )
    return render_template("parade/statuses.html", rows=rows, today=today)


@bp.route("/statuses/new", methods=["GET", "POST"])
@require(policy.can_key_parade)
def status_new():
    form = StatusEntryForm()
    _set_status_person_choices(form)
    if form.validate_on_submit():
        row = StatusEntry(
            person_id=form.person_id.data,
            type=StatusType(form.type.data),
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            day_part=DayPart(form.day_part.data),
            in_camp=_resolve_in_camp(form.type.data, form.in_camp.data),
            remarks=(form.remarks.data or "").strip() or None,
            created_by_id=current_user.id,
        )
        db.session.add(row)
        db.session.commit()
        flash("Status keyed.", "success")
        return redirect(url_for("parade.statuses_list"))
    return render_template("parade/status_form.html", form=form, row=None)


@bp.route("/statuses/<int:entry_id>/edit", methods=["GET", "POST"])
@require(policy.can_key_parade)
def status_edit(entry_id):
    row = db.session.get(StatusEntry, entry_id) or abort(404)
    form = StatusEntryForm(obj=row)
    _set_status_person_choices(form)
    if not form.is_submitted():
        # obj= fills plain columns (person_id/start_date/end_date/remarks)
        # straight away; enum-backed fields need their .value re-coerced
        # (same pattern as admin/person_edit). in_camp prefills to the
        # explicit stored value, never DEFAULT — the row is the truth.
        form.type.data = row.type.value
        form.day_part.data = row.day_part.value
        form.in_camp.data = "IN" if row.in_camp else "OUT"
    if form.validate_on_submit():
        row.person_id = form.person_id.data
        row.type = StatusType(form.type.data)
        row.start_date = form.start_date.data
        row.end_date = form.end_date.data
        row.day_part = DayPart(form.day_part.data)
        row.in_camp = _resolve_in_camp(form.type.data, form.in_camp.data)
        row.remarks = (form.remarks.data or "").strip() or None
        db.session.commit()
        flash("Saved.", "success")
        return redirect(url_for("parade.statuses_list"))
    return render_template("parade/status_form.html", form=form, row=row)


@bp.route("/statuses/<int:entry_id>/end-today", methods=["POST"])
@require(policy.can_key_parade)
def status_end_today(entry_id):
    row = db.session.get(StatusEntry, entry_id) or abort(404)
    today = today_sgt()
    if not (row.start_date <= today <= row.end_date):
        # Decision (e): the COS adds/ends/overrides, never re-keys — a future
        # entry isn't "ending today", it hasn't started being true yet.
        flash("Only entries covering today can be ended today.", "error")
        return redirect(url_for("parade.statuses_list"))
    row.end_date = today
    db.session.commit()
    flash("Ended today — it will no longer cover tomorrow.", "success")
    return redirect(url_for("parade.statuses_list"))


# --- Direct absences (S3-keyed absences for regulars) -----------------------

def _set_regular_choices(form):
    # NSFs go through the request flow (owner decision b); restricting choices
    # to REGULAR — computed fresh per request — IS the server-side re-check:
    # a hand-built POST naming an NSF's id fails WTForms' choice validation.
    regulars = [p for p in event_service.active_roster() if p.service is Service.REGULAR]
    form.person_id.choices = [(p.id, f"{p.rank.value} {p.display_name}") for p in regulars]


@bp.route("/direct-absences")
@require(policy.can_key_direct_absence)
def direct_absences_list():
    today = today_sgt()
    rows = (
        db.session.query(DirectAbsence)
        .join(Person, DirectAbsence.person_id == Person.id)
        .filter(DirectAbsence.end_date >= today)
        .order_by(DirectAbsence.start_date)
        .all()
    )
    return render_template("parade/direct_absences.html", rows=rows, today=today)


@bp.route("/direct-absences/new", methods=["GET", "POST"])
@require(policy.can_key_direct_absence)
def direct_absence_new():
    form = DirectAbsenceForm()
    _set_regular_choices(form)
    if form.validate_on_submit():
        row = DirectAbsence(
            person_id=form.person_id.data,
            type=DirectAbsenceType(form.type.data),
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            day_part=DayPart(form.day_part.data),
            remarks=form.remarks.data.strip(),
            created_by_id=current_user.id,
        )
        db.session.add(row)
        db.session.commit()
        flash("Direct absence keyed.", "success")
        return redirect(url_for("parade.direct_absences_list"))
    return render_template("parade/direct_absence_form.html", form=form, row=None)


@bp.route("/direct-absences/<int:entry_id>/edit", methods=["GET", "POST"])
@require(policy.can_key_direct_absence)
def direct_absence_edit(entry_id):
    row = db.session.get(DirectAbsence, entry_id) or abort(404)
    form = DirectAbsenceForm(obj=row)
    _set_regular_choices(form)
    if not form.is_submitted():
        form.type.data = row.type.value
        form.day_part.data = row.day_part.value
    if form.validate_on_submit():
        row.person_id = form.person_id.data
        row.type = DirectAbsenceType(form.type.data)
        row.start_date = form.start_date.data
        row.end_date = form.end_date.data
        row.day_part = DayPart(form.day_part.data)
        row.remarks = form.remarks.data.strip()
        db.session.commit()
        flash("Saved.", "success")
        return redirect(url_for("parade.direct_absences_list"))
    return render_template("parade/direct_absence_form.html", form=form, row=row)


@bp.route("/direct-absences/<int:entry_id>/end-today", methods=["POST"])
@require(policy.can_key_direct_absence)
def direct_absence_end_today(entry_id):
    row = db.session.get(DirectAbsence, entry_id) or abort(404)
    today = today_sgt()
    if not (row.start_date <= today <= row.end_date):
        flash("Only entries covering today can be ended today.", "error")
        return redirect(url_for("parade.direct_absences_list"))
    row.end_date = today
    db.session.commit()
    flash("Ended today — it will no longer cover tomorrow.", "success")
    return redirect(url_for("parade.direct_absences_list"))
