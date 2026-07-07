from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.parade import bp
from app.blueprints.parade.forms import DirectAbsenceForm, FpQuickAddForm, StatusEntryForm
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import (
    DayPart,
    DirectAbsenceType,
    LeaveType,
    ParadeVariant,
    STATUS_IN_CAMP_DEFAULT,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import DirectAbsence, ParadeSnapshot, Person, StatusEntry
from app.services import event_service, parade_service, presence_service


def _set_status_person_choices(form):
    # Request-time roster, not class-level, same reasoning as calendar's
    # _set_people_choices — who's active changes day to day. Shared by the
    # statuses form and the morning-parade quick-add (both key a StatusEntry).
    form.person_id.choices = [
        (p.id, f"{p.rank.value} {p.display_name}") for p in event_service.active_roster()
    ]


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


def _parse_day(raw: str, default: date = None) -> date:
    # Shared away/morning convention: a bad or missing ?date= falls back to a
    # page-specific default rather than 400ing — the page must always render
    # something. `default` lets the COS message page fall back to tomorrow
    # (compiled D-1, assumption 4) while every other page keeps falling back
    # to today.
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return default if default is not None else today_sgt()


def _validate_cos_person(raw, roster=None):
    """Resolve a `cos=` id (query or posted) to an active Person, else
    current_user. A keying mistake here costs one reload (P4's duty roster
    will auto-fill this), so we never 400 — invalid/inactive falls back
    silently, and the finalize route re-runs this same check server-side so a
    tampered hidden field can't name someone who isn't on the active roster.
    `roster` lets a caller that already fetched the active roster (the GET
    page, for its selector) pass it in rather than querying twice.
    """
    try:
        cos_id = int(raw)
    except (TypeError, ValueError):
        return current_user
    roster = roster if roster is not None else event_service.active_roster()
    person = next((p for p in roster if p.id == cos_id), None)
    return person or current_user


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
    # One pipeline for page, finalize, and meals (addendum A2). On imbalance
    # the template renders the error card and no <pre> — a wrong document is
    # worse than none (plan).
    built = parade_service.build_doc(day, ParadeVariant.MORNING)
    conflicts = _conflict_lines(built.pairs)

    fp_form = None
    fp_rows = ()
    if policy.can_key_parade(current_user):
        fp_form = FpQuickAddForm()
        _set_status_person_choices(fp_form)
        fp_rows = _fp_rows(day)

    return render_template(
        "parade/morning.html",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
        fp_form=fp_form,
        fp_rows=fp_rows,
    )


@bp.route("/morning/fp", methods=["POST"])
@require(policy.can_key_parade)
def morning_fp_new():
    day = _parse_day(request.form.get("date", ""))
    form = FpQuickAddForm()
    _set_status_person_choices(form)
    if form.validate_on_submit():
        row = StatusEntry(
            person_id=form.person_id.data,
            type=StatusType.OTHER,
            start_date=day,
            end_date=day,
            day_part=DayPart.FULL,
            in_camp=True,
            remarks=form.reason.data.strip(),
            created_by_id=current_user.id,
        )
        db.session.add(row)
        db.session.commit()
        flash("Added.", "success")
    else:
        flash("Could not add — check the person and reason.", "error")
    return redirect(url_for("parade.morning", date=day.isoformat()))


@bp.route("/morning/fp/<int:entry_id>/remove", methods=["POST"])
@require(policy.can_key_parade)
def morning_fp_remove(entry_id):
    day = _parse_day(request.form.get("date", ""))
    row = db.session.get(StatusEntry, entry_id)
    # Guard: only a same-shaped quick-add row for the page the keyer is
    # actually viewing may be hard-deleted here — this is a same-morning
    # correction of a seconds-old slip, not general status deletion (P3a.8's
    # snapshots protect finalized documents; this route never touches those).
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


@bp.route("/morning/finalize", methods=["POST"])
@require(policy.can_key_parade)
def morning_finalize():
    day = _parse_day(request.form.get("date", ""))
    # Recompute server-side through the same build_doc the GET page uses —
    # never trust the posted body for the archival record, or a tampered
    # hidden field could falsify what the app actually finalized.
    built = parade_service.build_doc(day, ParadeVariant.MORNING)
    if built.imbalance:
        flash(f"Cannot finalize — parade state out of balance: {built.imbalance}", "error")
        return redirect(url_for("parade.morning", date=day.isoformat()))
    snap = parade_service.finalize(day, ParadeVariant.MORNING, built.text, current_user)
    flash("Finalized and copied.", "success")
    return redirect(url_for("parade.snapshot_view", snapshot_id=snap.id))


@bp.route("/cos-message")
@login_required
def cos_message():
    # Compiled the evening before, forecasting the next duty day (assumption
    # 4) — the one page whose date default is tomorrow, not today.
    day = _parse_day(request.args.get("date", ""), default=today_sgt() + timedelta(days=1))
    roster = event_service.active_roster()
    cos_person = _validate_cos_person(request.args.get("cos", ""), roster)
    built = parade_service.build_doc(day, ParadeVariant.COS_MESSAGE, cos_person=cos_person)
    conflicts = _conflict_lines(built.pairs)

    return render_template(
        "parade/cos_message.html",
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


@bp.route("/cos-message/finalize", methods=["POST"])
@require(policy.can_key_parade)
def cos_message_finalize():
    day = _parse_day(request.form.get("date", ""), default=today_sgt() + timedelta(days=1))
    # Re-validate the posted cos id against the active roster here too — never
    # trust the hidden field, exactly like the recompute below never trusts
    # posted text.
    cos_person = _validate_cos_person(request.form.get("cos", ""))
    built = parade_service.build_doc(day, ParadeVariant.COS_MESSAGE, cos_person=cos_person)
    if built.imbalance:
        flash(f"Cannot finalize — parade state out of balance: {built.imbalance}", "error")
        return redirect(url_for("parade.cos_message", date=day.isoformat(), cos=cos_person.id))
    snap = parade_service.finalize(day, ParadeVariant.COS_MESSAGE, built.text, current_user)
    flash("Finalized and copied.", "success")
    return redirect(url_for("parade.snapshot_view", snapshot_id=snap.id))


@bp.route("/roll-call")
@login_required
def roll_call():
    day = _parse_day(request.args.get("date", ""))
    built = parade_service.build_doc(day, ParadeVariant.ROLL_CALL)
    conflicts = _conflict_lines(built.pairs)

    return render_template(
        "parade/roll_call.html",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
    )


@bp.route("/roll-call/finalize", methods=["POST"])
@require(policy.can_key_parade)
def roll_call_finalize():
    day = _parse_day(request.form.get("date", ""))
    # Recompute server-side through the same build_doc the GET page uses (same
    # posture as morning_finalize) — never trust the posted body.
    built = parade_service.build_doc(day, ParadeVariant.ROLL_CALL)
    if built.imbalance:
        flash(f"Cannot finalize — parade state out of balance: {built.imbalance}", "error")
        return redirect(url_for("parade.roll_call", date=day.isoformat()))
    snap = parade_service.finalize(day, ParadeVariant.ROLL_CALL, built.text, current_user)
    flash("Finalized and copied.", "success")
    return redirect(url_for("parade.snapshot_view", snapshot_id=snap.id))


# --- Snapshots (append-only finalize archive) --------------------------------

@bp.route("/snapshots")
@login_required
def snapshots_list():
    # Any logged-in user may view the archive — it's a read of history, not a
    # keying surface.
    rows = parade_service.snapshots()
    return render_template("parade/snapshots.html", rows=rows)


@bp.route("/snapshots/<int:snapshot_id>")
@login_required
def snapshot_view(snapshot_id):
    snap = db.session.get(ParadeSnapshot, snapshot_id) or abort(404)
    return render_template("parade/snapshot_detail.html", snap=snap)


# --- Statuses (MC/course/briefing/site-testing/other) -----------------------

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
