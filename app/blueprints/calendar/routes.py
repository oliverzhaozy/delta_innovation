import calendar as stdlib_calendar
from datetime import date, datetime, time

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.calendar import bp
from app.blueprints.calendar.forms import EventForm
from app.domain import policy
from app.domain.dates import iter_days, today_sgt
from app.domain.types import Calendar, ParticipantCategory
from app.extensions import db
from app.models import Event, EventParticipant
from app.services import event_service, presence_service


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
    # changes day to day, unlike the fixed category choices.
    choices = [(p.id, f"{p.rank.value} {p.display_name}") for p in event_service.active_roster()]
    form.include_people.choices = choices
    form.except_people.choices = choices


def _participant_rows_from(form):
    # Wholesale replacement, not a diff — the delete-orphan cascade on
    # Event.participants makes `event.participants = [...]` safe (P2.2).
    rows = [EventParticipant(category=ParticipantCategory(v), include=True) for v in form.categories.data]
    rows += [EventParticipant(person_id=pid, include=True) for pid in form.include_people.data]
    rows += [EventParticipant(person_id=pid, include=False) for pid in form.except_people.data]
    return rows


def _populate_participant_fields(form, event):
    form.categories.data = [
        r.category.value for r in event.participants if r.category is not None and r.include
    ]
    form.include_people.data = [
        r.person_id for r in event.participants if r.person_id is not None and r.include
    ]
    form.except_people.data = [
        r.person_id for r in event.participants if r.person_id is not None and not r.include
    ]


def _month_bounds(year, month):
    start = date(year, month, 1)
    end_exclusive = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end_exclusive


def _adjacent_ym(year, month, delta):
    # delta is +-1 month; only ever called with |delta| == 1 so no general
    # modular-arithmetic case is needed.
    if delta == 1:
        return (year + 1, 1) if month == 12 else (year, month + 1)
    return (year - 1, 12) if month == 1 else (year, month - 1)


@bp.route("/month")
@login_required
def month():
    raw = request.args.get("ym", "")
    today = today_sgt()
    year, month_num = today.year, today.month
    if raw:
        try:
            year_str, month_str = raw.split("-")
            year, month_num = int(year_str), int(month_str)
            month_start, month_end_exclusive = _month_bounds(year, month_num)
        except ValueError:
            # Bad ?ym= mirrors parade.away's bad ?date= convention (fall back
            # to today rather than 404 — checked, the away board doesn't 404).
            year, month_num = today.year, today.month
            month_start, month_end_exclusive = _month_bounds(year, month_num)
    else:
        month_start, month_end_exclusive = _month_bounds(year, month_num)
    month_end_inclusive = date.fromordinal(month_end_exclusive.toordinal() - 1)

    show_arctic = policy.can_view_arctic(current_user)
    events = (
        db.session.query(Event)
        .filter(
            Event.start_dt < datetime.combine(month_end_exclusive, time.min),
            Event.end_dt > datetime.combine(month_start, time.min),
        )
        .order_by(Event.start_dt)
        .all()
    )
    events_by_day = {d: [] for d in iter_days(month_start, month_end_inclusive)}
    for event in events:
        # ARCTIC filtered server-side, same rule as the list/detail routes —
        # never trust the template to hide rows it shouldn't have.
        if event.calendar is Calendar.ARCTIC and not show_arctic:
            continue
        # .date() on both ends, inclusive: an event ending at 00:00 still
        # occupies that calendar day. Acceptable simplification for a chip
        # display — not the precise clash-check semantics of a later task.
        first = max(event.start_dt.date(), month_start)
        last = min(event.end_dt.date(), month_end_inclusive)
        for d in iter_days(first, last):
            events_by_day[d].append(event)

    away_counts = presence_service.absences_between(month_start, month_end_inclusive)

    weeks = []
    for week in stdlib_calendar.Calendar(firstweekday=0).monthdatescalendar(year, month_num):
        cells = []
        for d in week:
            in_month = d.month == month_num and d.year == year
            cells.append(
                {
                    "date": d,
                    "in_month": in_month,
                    # Adjacent-month padding cells get no chips at all (TECH_PLAN cut).
                    "events": events_by_day.get(d, []) if in_month else [],
                    "away": len(away_counts.get(d, [])) if in_month else 0,
                }
            )
        weeks.append(cells)

    prev_ym = "%04d-%02d" % _adjacent_ym(year, month_num, -1)
    next_ym = "%04d-%02d" % _adjacent_ym(year, month_num, 1)

    return render_template(
        "calendar/month.html",
        month_start=month_start,
        weekday_labels=list(stdlib_calendar.day_abbr),
        weeks=weeks,
        prev_ym=prev_ym,
        next_ym=next_ym,
        today_ym="%04d-%02d" % (today.year, today.month),
        show_arctic=show_arctic,
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
    if form.validate_on_submit():
        event = Event(
            calendar=Calendar(form.calendar.data),
            title=form.title.data.strip(),
            start_dt=form.start_dt.data,
            end_dt=form.end_dt.data,
            notes=(form.notes.data or "").strip() or None,
            created_by_id=current_user.id,
        )
        event.participants = _participant_rows_from(form)
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
    _set_people_choices(form)
    if not form.is_submitted():
        # obj= fills the calendar SelectField with the enum instance; it
        # needs the plain string value (same pattern as admin/person_edit).
        form.calendar.data = event.calendar.value
        _populate_participant_fields(form, event)
    if form.validate_on_submit():
        event.calendar = Calendar(form.calendar.data)
        event.title = form.title.data.strip()
        event.start_dt = form.start_dt.data
        event.end_dt = form.end_dt.data
        event.notes = (form.notes.data or "").strip() or None
        event.participants = _participant_rows_from(form)
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
