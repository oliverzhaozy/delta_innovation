from datetime import date, datetime, time

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.calendar import bp
from app.blueprints.calendar.forms import EventForm
from app.domain import events, policy
from app.domain.types import ArcticLabel, Calendar, ParticipantCategory, TpLabel
from app.extensions import db
from app.models import Event, EventParticipant
from app.services import calendar_month, event_service


def _events_for(calendar):
    return (
        db.session.query(Event)
        .filter_by(calendar=calendar)
        .order_by(Event.start_dt.desc())
        .all()
    )


def _list_endpoint(calendar):
    return "calendar.arctic_list" if calendar is Calendar.ARCTIC else "calendar.tp_list"


def _set_people_choices(form):
    # Request-time roster, not class-level — who's active/what platoon
    # changes day to day, unlike the fixed category choices. Only sets the
    # `people` choices so SelectMultipleField.pre_validate accepts the ids the
    # grouped dropdowns render (an inactive/unknown id fails as a clean field
    # error rather than reaching the DB).
    form.people.choices = [
        (p.id, f"{p.rank.value} {p.display_name}") for p in event_service.active_roster()
    ]


def _participant_rows_from(form):
    # Wholesale replacement, not a diff — the delete-orphan cascade on
    # Event.participants makes `event.participants = [...]` safe (P2.2).
    #
    # "ALL" is a form-level pseudo-choice: expand it to NSF+REGULAR (the
    # resolver's whole-company idiom), then dedupe the category VALUES into a
    # set before building rows — otherwise ALL+NSF would emit two NSF rows and
    # violate uq_participant_event_category (a 500). The set() also closes a
    # crafted `categories=NSF&categories=NSF` POST.
    values = set(form.categories.data)
    if "ALL" in values:
        values.discard("ALL")
        values.update({ParticipantCategory.NSF.value, ParticipantCategory.REGULAR.value})
    rows = [EventParticipant(category=ParticipantCategory(v), include=True) for v in values]
    # Dedupe person ids with set() too: the checkbox UI renders a person in
    # both their service and platoon group, so a no-JS user can legitimately
    # tick the same person twice — two rows would violate
    # uq_participant_event_person. Only include rows now (except was cut, UI-11).
    rows += [EventParticipant(person_id=pid, include=True) for pid in set(form.people.data)]
    return rows


def _populate_participant_fields(form, event):
    # Collapse the stored NSF+REGULAR pair back into the "ALL" pseudo-choice so
    # the round-trip is stable: {NSF,REGULAR} ⊆ stored shows ALL checked with
    # NSF/REGULAR themselves unchecked; anything else shows as-is.
    stored = {
        r.category.value for r in event.participants if r.category is not None and r.include
    }
    selected = []
    nsf_regular = {ParticipantCategory.NSF.value, ParticipantCategory.REGULAR.value}
    if nsf_regular <= stored:
        selected.append("ALL")
        stored = stored - nsf_regular
    selected += [c.value for c in ParticipantCategory if c.value in stored]
    form.categories.data = selected
    form.people.data = [
        r.person_id for r in event.participants if r.person_id is not None and r.include
    ]


def _set_label_choices(form):
    # All labels from both calendars in one select; the JS sprinkle filters the
    # visible options to the chosen calendar, and validate_label enforces the
    # pairing server-side. "" is the optional "no label" choice.
    form.label.choices = (
        [("", "— none —")]
        + [(m.value, m.value) for m in TpLabel]
        + [(m.value, m.value) for m in ArcticLabel]
    )


def _label_calendars():
    # value -> calendar value ("TP"/"ARCTIC"), so the form's JS can hide labels
    # that don't belong to the currently-selected calendar.
    mapping = {m.value: Calendar.TP.value for m in TpLabel}
    mapping.update({m.value: Calendar.ARCTIC.value for m in ArcticLabel})
    return mapping


def _event_times(form):
    # All-day owns its time convention in one place (domain.events); a timed
    # event keeps exactly what was entered.
    if form.all_day.data:
        return events.all_day_bounds(form.start_dt.data.date(), form.end_dt.data.date())
    return form.start_dt.data, form.end_dt.data


def _prefill_date(form, raw):
    # A day-click on the month grid lands on /calendar/new?date=YYYY-MM-DD; seed
    # the form to that day (08:00–09:00 default). A bad/missing date falls through
    # to a blank form — same forgiving convention as parade.away's ?date=.
    if not raw:
        return
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return
    form.start_dt.data = datetime.combine(day, time(8, 0))
    form.end_dt.data = datetime.combine(day, time(9, 0))


@bp.route("/month")
@login_required
def month():
    return render_template(
        "calendar/month.html",
        **calendar_month.build_month_context(current_user, request.args.get("ym", "")),
    )


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
    return render_template(
        "calendar/detail.html", event=event, resolved=event_service.resolve_participants(event)
    )


@bp.route("/new", methods=["GET", "POST"])
@require(policy.can_edit_events)
def new():
    form = EventForm()
    _set_people_choices(form)
    _set_label_choices(form)
    if request.method == "GET":
        _prefill_date(form, request.args.get("date"))
    if form.validate_on_submit():
        start_dt, end_dt = _event_times(form)
        event = Event(
            calendar=Calendar(form.calendar.data),
            title=form.title.data.strip(),
            all_day=form.all_day.data,
            start_dt=start_dt,
            end_dt=end_dt,
            label=form.label.data or None,
            notes=(form.notes.data or "").strip() or None,
            created_by_id=current_user.id,
        )
        event.participants = _participant_rows_from(form)
        db.session.add(event)
        db.session.commit()
        flash("Event created.", "success")
        return redirect(url_for("calendar.detail", event_id=event.id))
    return render_template(
        "calendar/form.html",
        form=form,
        event=None,
        label_calendars=_label_calendars(),
        picker_groups=event_service.picker_groups(),
        legacy_excludes=[],
    )


@bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
@require(policy.can_edit_events)
def edit(event_id):
    event = db.session.get(Event, event_id) or abort(404)
    form = EventForm(obj=event)
    _set_people_choices(form)
    _set_label_choices(form)
    if not form.is_submitted():
        # obj= fills the calendar SelectField with the enum instance; it
        # needs the plain string value (same pattern as admin/person_edit).
        # all_day/label are plain columns, so obj= populates them directly.
        form.calendar.data = event.calendar.value
        _populate_participant_fields(form, event)
    if form.validate_on_submit():
        start_dt, end_dt = _event_times(form)
        event.calendar = Calendar(form.calendar.data)
        event.title = form.title.data.strip()
        event.all_day = form.all_day.data
        event.start_dt = start_dt
        event.end_dt = end_dt
        event.label = form.label.data or None
        event.notes = (form.notes.data or "").strip() or None
        # Flush the delete-orphan of the old rows BEFORE inserting the new ones:
        # a category that survives the edit (the ALL round-trip, or an
        # unchanged group) would otherwise insert its new row while the old one
        # still exists and trip uq_participant_event_category. Clearing then
        # flushing forces the DELETEs ahead of the INSERTs.
        event.participants.clear()
        db.session.flush()
        event.participants = _participant_rows_from(form)
        db.session.commit()
        flash("Event updated.", "success")
        return redirect(url_for("calendar.detail", event_id=event.id))
    return render_template(
        "calendar/form.html",
        form=form,
        event=event,
        label_calendars=_label_calendars(),
        picker_groups=event_service.picker_groups(),
        # Pre-UI-11 events may still carry person exclude rows; surface them so
        # the editor knows saving will drop them (the picker no longer emits
        # exclude rows). This never shows for events created under UI-11.
        legacy_excludes=[
            r.person for r in event.participants if r.person_id is not None and not r.include
        ],
    )


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
