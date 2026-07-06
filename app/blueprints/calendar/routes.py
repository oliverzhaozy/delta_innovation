from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.calendar import bp
from app.blueprints.calendar.forms import EventForm
from app.domain import policy
from app.domain.types import Calendar
from app.extensions import db
from app.models import Event


def _events_for(calendar):
    return (
        db.session.query(Event)
        .filter_by(calendar=calendar)
        .order_by(Event.start_dt.desc())
        .all()
    )


def _list_endpoint(calendar):
    return "calendar.arctic_list" if calendar is Calendar.ARCTIC else "calendar.tp_list"


@bp.route("/tp")
@login_required
def tp_list():
    # Any logged-in user — TP has no gating (TECH_PLAN RBAC line).
    return render_template(
        "calendar/list.html", events=_events_for(Calendar.TP), calendar=Calendar.TP
    )


@bp.route("/arctic")
@require(policy.can_view_arctic)
def arctic_list():
    return render_template(
        "calendar/list.html", events=_events_for(Calendar.ARCTIC), calendar=Calendar.ARCTIC
    )


@bp.route("/<int:event_id>")
@login_required
def detail(event_id):
    event = db.session.get(Event, event_id) or abort(404)
    # Object-level check: a TP-visible user must not open an ARCTIC event by
    # URL just because the route itself only requires login.
    if event.calendar is Calendar.ARCTIC and not policy.can_view_arctic(current_user):
        abort(403)
    return render_template("calendar/detail.html", event=event)


@bp.route("/new", methods=["GET", "POST"])
@require(policy.can_edit_events)
def new():
    form = EventForm()
    if form.validate_on_submit():
        event = Event(
            calendar=Calendar(form.calendar.data),
            title=form.title.data.strip(),
            start_dt=form.start_dt.data,
            end_dt=form.end_dt.data,
            notes=(form.notes.data or "").strip() or None,
            created_by_id=current_user.id,
        )
        db.session.add(event)
        db.session.commit()
        flash("Event created.", "success")
        return redirect(url_for("calendar.detail", event_id=event.id))
    return render_template("calendar/form.html", form=form, event=None)


@bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
@require(policy.can_edit_events)
def edit(event_id):
    event = db.session.get(Event, event_id) or abort(404)
    form = EventForm(obj=event)
    if not form.is_submitted():
        # obj= fills the calendar SelectField with the enum instance; it
        # needs the plain string value (same pattern as admin/person_edit).
        form.calendar.data = event.calendar.value
    if form.validate_on_submit():
        event.calendar = Calendar(form.calendar.data)
        event.title = form.title.data.strip()
        event.start_dt = form.start_dt.data
        event.end_dt = form.end_dt.data
        event.notes = (form.notes.data or "").strip() or None
        db.session.commit()
        flash("Event updated.", "success")
        return redirect(url_for("calendar.detail", event_id=event.id))
    return render_template("calendar/form.html", form=form, event=event)


@bp.route("/<int:event_id>/delete", methods=["POST"])
@require(policy.can_edit_events)
def delete(event_id):
    event = db.session.get(Event, event_id) or abort(404)
    calendar = event.calendar
    # Hard delete — participant rows cascade via the model relationship (P2.2).
    db.session.delete(event)
    db.session.commit()
    flash("Event deleted.", "success")
    return redirect(url_for(_list_endpoint(calendar)))
