from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.parade import bp
from app.blueprints.parade.forms import FpBulkAddForm, StatusEntryForm
from app.domain import participants, presence
from app.domain.dates import today_sgt
from app.domain.parade import parade_line
from app.domain.types import (
    ALLOWED_OVERRIDE_TARGETS,
    DayPart,
    LeaveType,
    OverrideCategory,
    ParadeVariant,
    ParticipantCategory,
    STATUS_IN_CAMP_DEFAULT,
    StatusType,
)
from app.extensions import db
from app.models import Person, StatusEntry
from app.services import duty_service, event_service, parade_service


def _variant_day(key):
    """The ONE owner of the page-date convention the override routes act on:
    morning and roll call are today's documents; the COS message is compiled the
    evening before for tomorrow's duty day. An unrecognised key is a stale or
    tampered POST — 400, never a silent default onto some date.
    Returns (ParadeVariant, date).
    """
    today = today_sgt()
    mapping = {
        "morning": (ParadeVariant.MORNING, today),
        "roll_call": (ParadeVariant.ROLL_CALL, today),
        "cos": (ParadeVariant.COS_MESSAGE, today + timedelta(days=1)),
    }
    if key not in mapping:
        abort(400)
    return mapping[key]


def _variant_redirect(variant, cos_name=None):
    """Send an override POST back to the page it acted on. The COS page carries
    its typed `cos_name` through so the redirected render rebuilds the very same
    document the drag was performed against."""
    if variant is ParadeVariant.MORNING:
        return redirect(url_for("parade.morning"))
    if variant is ParadeVariant.ROLL_CALL:
        return redirect(url_for("parade.roll_call"))
    return redirect(
        url_for("parade.cos_message", **({"cos_name": cos_name} if cos_name else {}))
    )


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


COS_DISPLAY_MAX = 60


def _cos_display(raw) -> str:
    """The greeting's "RANK NAME" string, from the free-text `cos_name=` param.

    Free text, not a roster pick (owner decision 2026-07-26): the COS of a given
    night is not always someone this app holds, and the default is simply whoever
    is looking at the page — no confirmed-roster autofill. Whitespace-collapsed,
    length-capped, and uppercased so a pasted blob cannot bend the greeting out
    of the WhatsApp format; blank or missing falls back to the logged-in user.
    """
    typed = " ".join((raw or "").split())[:COS_DISPLAY_MAX].upper()
    return typed or parade_line(current_user)


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
    day = today_sgt()
    # One pipeline for the page and meals (addendum A2). On imbalance the
    # template renders the error card and no <pre> — a wrong document is
    # worse than none (plan).
    built = parade_service.build_doc(day, ParadeVariant.MORNING)
    conflicts = _conflict_lines(built.pairs)
    can_adjust = duty_service.can_key_parade_today(current_user)

    fp_form = None
    fp_rows = ()
    picker_groups = ()
    command_ids = frozenset()
    if can_adjust:
        fp_form = FpBulkAddForm()
        _set_fp_people_choices(fp_form)
        fp_rows = _fp_rows(day)
        picker_groups = event_service.picker_groups()
        command_ids = event_service.command_person_ids()

    return render_template(
        "parade/state.html",
        doc="morning",
        day=day,
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
        fp_form=fp_form,
        fp_rows=fp_rows,
        picker_groups=picker_groups,
        command_ids=command_ids,
        can_adjust=can_adjust,
        has_overrides=built.has_overrides,
    )


@bp.route("/morning/fp", methods=["POST"])
@require(duty_service.can_key_parade_today)
def morning_fp_new():
    day = today_sgt()
    form = FpBulkAddForm()
    _set_fp_people_choices(form)
    if not form.validate_on_submit():
        flash("Could not add — check the selection and reason.", "error")
        return redirect(url_for("parade.morning"))

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
        return redirect(url_for("parade.morning"))

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
    return redirect(url_for("parade.morning"))


@bp.route("/morning/fp/<int:entry_id>/remove", methods=["POST"])
@require(duty_service.can_key_parade_today)
def morning_fp_remove(entry_id):
    day = today_sgt()
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
    return redirect(url_for("parade.morning"))


@bp.route("/cos-message")
@login_required
def cos_message():
    # Compiled the evening before, forecasting the next duty day (assumption
    # 4) — the one page fixed to tomorrow, not today.
    day = today_sgt() + timedelta(days=1)
    cos_name = request.args.get("cos_name", "")
    built = parade_service.build_doc(
        day, ParadeVariant.COS_MESSAGE, cos_display=_cos_display(cos_name)
    )
    conflicts = _conflict_lines(built.pairs)

    return render_template(
        "parade/state.html",
        doc="cos",
        day=day,
        cos_name=cos_name,
        cos_placeholder=f"{parade_line(current_user)} (you)",
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
        can_adjust=duty_service.can_key_parade_today(current_user),
        has_overrides=built.has_overrides,
    )


@bp.route("/roll-call")
@login_required
def roll_call():
    day = today_sgt()
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
        text=built.text,
        imbalance=built.imbalance,
        conflicts=conflicts,
        absent_holders=absent_holders,
        can_adjust=duty_service.can_key_parade_today(current_user),
        has_overrides=built.has_overrides,
    )


# --- Drag-and-drop overrides (recategorize one person on one document) --------

@bp.route("/override", methods=["POST"])
@require(duty_service.can_key_parade_today)
def override():
    # Same keying gate as every other parade write. The variant/date come from
    # the shared _variant_day owner; the target and person are validated HERE
    # against the variant's allowed categories and today's active roster, so a
    # tampered or stale POST can never store an off-roster person or a category
    # that variant forbids (apply_overrides would raise on the latter).
    variant, day = _variant_day(request.form.get("variant", ""))
    cos_name = request.form.get("cos_name", "")
    try:
        person_id = int(request.form.get("person_id", ""))
    except (TypeError, ValueError):
        person_id = None
    try:
        target = OverrideCategory(request.form.get("target", ""))
    except ValueError:
        target = None
    roster_ids = {p.id for p in event_service.active_roster()}
    if (
        person_id is None
        or person_id not in roster_ids
        or target is None
        or target not in ALLOWED_OVERRIDE_TARGETS[variant]
    ):
        flash("Could not move — check the selection.", "error")
        return _variant_redirect(variant, cos_name)
    parade_service.set_override(
        day, variant, person_id, target, created_by_id=current_user.id
    )
    db.session.commit()
    return _variant_redirect(variant, cos_name)


@bp.route("/override/reset", methods=["POST"])
@require(duty_service.can_key_parade_today)
def override_reset():
    variant, day = _variant_day(request.form.get("variant", ""))
    count = parade_service.clear_overrides(day, variant)
    db.session.commit()
    flash(f"Reset {count} move{'s' if count != 1 else ''}.", "success")
    return _variant_redirect(variant, request.form.get("cos_name", ""))


# --- Statuses (MC/other) ------------------------------------------------------

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
