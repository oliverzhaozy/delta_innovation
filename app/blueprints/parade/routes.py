from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.parade import bp
from app.blueprints.parade.forms import DirectAbsenceForm, FpBulkAddForm, StatusEntryForm
from app.domain import participants, policy, presence
from app.domain.dates import today_sgt
from app.domain.types import (
    DayPart,
    DirectAbsenceType,
    LeaveType,
    ParadeVariant,
    ParticipantCategory,
    STATUS_IN_CAMP_DEFAULT,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import DirectAbsence, Person, StatusEntry
from app.services import duty_service, event_service, parade_service


def _set_fp_people_choices(form):
    # Same request-time reasoning as _set_status_person_choices below: the
    # picker's person checkboxes must validate against today's active roster,
    # so an inactive/unknown id fails as a clean field error, never a write.
    form.people.choices = [
        (p.id, f"{p.rank.value} {p.display_name}") for p in event_service.active_roster()
    ]


def _set_status_person_choices(form):
    # Request-time roster, not class-level, same reasoning as calendar's
    # _set_people_choices — who's active changes day to day.
    form.person_id.choices = [
        (p.id, f"{p.rank.value} {p.display_name}") for p in event_service.active_roster()
    ]


def _parse_day(raw: str, default: date = None) -> date:
    # The parade pages' ?date= convention: a bad or missing ?date= falls back to
    # a page-specific default rather than 400ing — the page must always render
    # something. `default` lets the COS message page fall back to tomorrow
    # (compiled D-1, assumption 4) while every other page keeps falling back
    # to today.
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return default if default is not None else today_sgt()


def _validate_cos_person(raw, day, roster=None):
    """Resolve a `cos=` id (query or posted) to an active Person; fallback
    order is CONFIRMED COS of the page date, then current_user (P4.8 closes
    the P3 hook this function's comment has named since P3b.3). An explicit
    valid `?cos=` always wins — auto-fill must not override a deliberate
    hand-selection. Invalid or inactive ids never 400 — a keying mistake costs
    one reload — and resolving against the active roster means a tampered
    query value can't name someone off-roster. `roster` lets a caller that
    already fetched the active roster pass it in.
    """
    roster = roster if roster is not None else event_service.active_roster()
    try:
        cos_id = int(raw)
    except (TypeError, ValueError):
        cos_id = None
    if cos_id is not None:
        person = next((p for p in roster if p.id == cos_id), None)
        if person is not None:
            return person
    return duty_service.cos_of_day(day) or current_user


def _row_label(row) -> str:
    # Same discrimination domain.parade._absent_category uses (the enum class
    # of `row.type` is the one attribute every absence-making row shares):
    # LeaveType has no .label (OFF/OIL/LL/OL already read fine as bare values),
    # everything else exposes .label.
    kind = row.type
    return kind.value if isinstance(kind, LeaveType) else kind.label


def _row_range(row) -> str:
    start = row.start_date.strftime("%d %b")
    if row.end_date == row.start_date:
        return start
    return f"{start} – {row.end_date.strftime('%d %b')}"


def _conflict_lines(pairs):
    """One line per shadowed row, across every person whose resolution carries
    conflicts — the presence engine never drops a covering absence-making row,
    so the keyer must see what it hid behind the winner (plan: surfaced,
    never silently resolved).
    """
    lines = []
    for person, resolution in pairs:
        for shadowed in resolution.conflicts:
            lines.append(
                {
                    "person": person,
                    "winner_label": _row_label(resolution.row),
                    "winner_range": _row_range(resolution.row),
                    "shadow_label": _row_label(shadowed),
                    "shadow_range": _row_range(shadowed),
                }
            )
    return lines


def _fp_rows(day):
    # Defined by shape (OTHER + in_camp + single-day + start==end==day), not a
    # hidden flag — a quick-add IS just a StatusEntry of this shape, so the
    # list is a read of the same table the document itself reads.
    return (
        db.session.query(StatusEntry)
        .join(Person, StatusEntry.person_id == Person.id)
        .filter(
            StatusEntry.type == StatusType.OTHER,
            StatusEntry.in_camp.is_(True),
            StatusEntry.start_date == day,
            StatusEntry.end_date == day,
        )
        .order_by(Person.platoon.nulls_first(), Person.display_name)
        .all()
    )


@bp.route("/morning")
@login_required
def morning():
    day = _parse_day(request.args.get("date", ""))
    # One pipeline for the page and meals (addendum A2). On imbalance the
    # template renders the error card and no <pre> — a wrong document is
    # worse than none (plan).
    built = parade_service.build_doc(day, ParadeVariant.MORNING)
    conflicts = _conflict_lines(built.pairs)

    fp_form = None
    fp_rows = ()
    picker_groups = ()
    command_ids = frozenset()
    if duty_service.can_key_parade_today(current_user):
        fp_form = FpBulkAddForm()
        _set_fp_people_choices(fp_form)
        fp_rows = _fp_rows(day)
        picker_groups = event_service.picker_groups()
        command_ids = event_service.command_person_ids()

    return render_template(
        "parade/state.html",
        doc="morning",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
        fp_form=fp_form,
        fp_rows=fp_rows,
        picker_groups=picker_groups,
        command_ids=command_ids,
    )


@bp.route("/morning/fp", methods=["POST"])
@require(duty_service.can_key_parade_today)
def morning_fp_new():
    day = _parse_day(request.form.get("date", ""))
    form = FpBulkAddForm()
    _set_fp_people_choices(form)
    if not form.validate_on_submit():
        flash("Could not add — check the selection and reason.", "error")
        return redirect(url_for("parade.morning", date=day.isoformat()))

    # Categories expand to concrete people NOW (unlike calendar events, an FP
    # row is per-person state for one morning, so nothing category-shaped is
    # stored); ALL covers the whole active roster.
    roster = event_service.active_roster()
    values = set(form.categories.data)
    selected = set(form.people.data)
    if "ALL" in values:
        values.discard("ALL")
        selected.update(p.id for p in roster)
    selected.update(
        p.id
        for p in roster
        if any(participants.in_category(p, ParticipantCategory(v)) for v in values)
    )
    if not selected:
        flash("Select at least one person or group.", "error")
        return redirect(url_for("parade.morning", date=day.isoformat()))

    # Already-tagged people are skipped, never overwritten (owner decision
    # 2026-07-11) — Remove + re-add is how a keyed reason gets changed.
    existing = {row.person_id for row in _fp_rows(day)}
    reason = form.reason.data.strip()
    to_add = sorted(selected - existing)
    for person_id in to_add:
        db.session.add(
            StatusEntry(
                person_id=person_id,
                type=StatusType.OTHER,
                start_date=day,
                end_date=day,
                day_part=DayPart.FULL,
                in_camp=True,
                remarks=reason,
                created_by_id=current_user.id,
            )
        )
    db.session.commit()  # the whole batch lands or fails as one transaction
    skipped = len(selected & existing)
    message = f"Added {len(to_add)}."
    if skipped:
        message += f" Skipped {skipped} already tagged."
    flash(message, "success")
    return redirect(url_for("parade.morning", date=day.isoformat()))


@bp.route("/morning/fp/<int:entry_id>/remove", methods=["POST"])
@require(duty_service.can_key_parade_today)
def morning_fp_remove(entry_id):
    day = _parse_day(request.form.get("date", ""))
    row = db.session.get(StatusEntry, entry_id)
    # Guard: only a same-shaped quick-add row for the page the keyer is
    # actually viewing may be hard-deleted here — this is a same-morning
    # correction of a seconds-old slip, not general status deletion.
    is_quick_add = (
        row is not None
        and row.type is StatusType.OTHER
        and row.in_camp
        and row.start_date == row.end_date == day
    )
    if not is_quick_add:
        abort(404)
    db.session.delete(row)
    db.session.commit()
    flash("Removed.", "success")
    return redirect(url_for("parade.morning", date=day.isoformat()))


@bp.route("/cos-message")
@login_required
def cos_message():
    # Compiled the evening before, forecasting the next duty day (assumption
    # 4) — the one page whose date default is tomorrow, not today.
    day = _parse_day(request.args.get("date", ""), default=today_sgt() + timedelta(days=1))
    roster = event_service.active_roster()
    cos_person = _validate_cos_person(request.args.get("cos", ""), day, roster)
    built = parade_service.build_doc(day, ParadeVariant.COS_MESSAGE, cos_person=cos_person)
    conflicts = _conflict_lines(built.pairs)

    return render_template(
        "parade/state.html",
        doc="cos",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        cos_person=cos_person,
        roster=roster,
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
    )


@bp.route("/roll-call")
@login_required
def roll_call():
    day = _parse_day(request.args.get("date", ""))
    built = parade_service.build_doc(day, ParadeVariant.ROLL_CALL)
    conflicts = _conflict_lines(built.pairs)
    # The night this document covers is day−1 → day (A7 notice reads the same
    # duty date build_doc does).
    night_rows = duty_service.confirmed_on(day - timedelta(days=1))
    # Absent holders derive from built.pairs — those resolutions were computed
    # with the right duty_day; re-resolving here could disagree with the
    # document below the chrome.
    holders = {row.person_id: row for row in night_rows}
    absent_holders = [
        {"row": holders[person.id], "person": person, "label": _row_label(resolution.row)}
        for person, resolution in built.pairs
        if person.id in holders and resolution.state is presence.PresenceState.ABSENT
    ]

    return render_template(
        "parade/state.html",
        doc="roll_call",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
        absent_holders=absent_holders,
    )


# --- Statuses (MC/course/briefing/site-testing/other) -----------------------

def _resolve_in_camp(type_value, in_camp_choice):
    if in_camp_choice == "IN":
        return True
    if in_camp_choice == "OUT":
        return False
    return STATUS_IN_CAMP_DEFAULT[StatusType(type_value)]  # DEFAULT


@bp.route("/statuses")
@require(duty_service.can_key_parade_today)
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
@require(duty_service.can_key_parade_today)
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
@require(duty_service.can_key_parade_today)
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
@require(duty_service.can_key_parade_today)
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
