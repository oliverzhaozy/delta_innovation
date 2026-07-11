import secrets

from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.authz import require
from app.blueprints.admin import bp
from app.blueprints.admin.forms import PersonForm
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import (
    APPOINTMENT_ORDER,
    Appointment,
    CompanyRole,
    PENDING_STATUSES,
    RANK_ORDER,
    Rank,
    RequestStatus,
    Service,
)
from app.extensions import db
from app.models import LeaveRequest, Person


def _apply_form(person, form):
    person.username = form.username.data.strip().lower()
    person.display_name = form.display_name.data.strip()
    person.phone = (form.phone.data or "").strip() or None
    person.rank = Rank(form.rank.data)
    person.appointment = Appointment(form.appointment.data)
    person.company_role = CompanyRole(form.company_role.data) if form.company_role.data else None
    person.platoon = int(form.platoon.data) if form.platoon.data else None
    person.service = Service(form.service.data)
    person.stay_out = form.stay_out.data
    person.is_admin = form.is_admin.data
    person.is_active = form.is_active.data


def _username_taken(username, exclude_id=None):
    q = db.session.query(Person.id).filter_by(username=username)
    if exclude_id is not None:
        q = q.filter(Person.id != exclude_id)
    return q.first() is not None


@bp.route("/people")
@require(policy.can_manage_people)
def people():
    # Appointment then rank isn't an alphabetical order, so sort in Python by the
    # declared seniority maps (36 rows — a CASE ladder would just restate them).
    # Active first keeps ORD/posted-out members from interleaving the live roster.
    everyone = db.session.query(Person).all()
    everyone.sort(
        key=lambda p: (
            not p.is_active,
            APPOINTMENT_ORDER[p.appointment],
            -RANK_ORDER[p.rank],
            p.display_name,
        )
    )
    return render_template("admin/people.html", people=everyone)


@bp.route("/people/new", methods=["GET", "POST"])
@require(policy.can_manage_people)
def person_new():
    form = PersonForm()
    if form.validate_on_submit():
        username = form.username.data.strip().lower()
        if _username_taken(username):
            flash("That username is already taken.", "error")
        else:
            person = Person()
            _apply_form(person, form)
            temp_password = _issue_temp_password(person)
            db.session.add(person)
            db.session.commit()
            flash(
                f"Created {person.display_name}. Temporary password: {temp_password} "
                "(shown once — they must change it at first login).",
                "success",
            )
            return redirect(url_for("admin.people"))
    return render_template("admin/person_form.html", form=form, person=None)


@bp.route("/people/<int:person_id>", methods=["GET", "POST"])
@require(policy.can_manage_people)
def person_edit(person_id):
    person = db.session.get(Person, person_id) or abort(404)
    form = PersonForm(obj=person)
    if not form.is_submitted():
        # obj= fills SelectFields with enum instances; they need string values.
        form.rank.data = person.rank.value
        form.appointment.data = person.appointment.value
        form.service.data = person.service.value
        form.company_role.data = person.company_role.value if person.company_role else ""
        form.platoon.data = str(person.platoon) if person.platoon else ""
    if form.validate_on_submit():
        username = form.username.data.strip().lower()
        if _username_taken(username, exclude_id=person.id):
            flash("That username is already taken.", "error")
        else:
            _apply_form(person, form)
            db.session.commit()
            flash("Saved.", "success")
            return redirect(url_for("admin.people"))
    # Surface what deactivation would strand: pending requests and future
    # approved leave need voiding/cancelling first (TECH_PLAN P1.1).
    open_items = (
        db.session.query(LeaveRequest)
        .filter(
            LeaveRequest.person_id == person.id,
            db.or_(
                LeaveRequest.status.in_(PENDING_STATUSES),
                db.and_(
                    LeaveRequest.status == RequestStatus.APPROVED,
                    LeaveRequest.end_date >= today_sgt(),
                ),
            ),
        )
        .order_by(LeaveRequest.start_date)
        .all()
    )
    return render_template("admin/person_form.html", form=form, person=person, open_items=open_items)


@bp.route("/people/<int:person_id>/delete", methods=["POST"])
@require(policy.can_manage_people)
def person_delete(person_id):
    person = db.session.get(Person, person_id) or abort(404)
    # Deleting the row you're signed in as would strand the session; block it.
    if person.id == current_user.id:
        flash("You can't delete your own account.", "error")
        return redirect(url_for("admin.person_edit", person_id=person.id))
    name = person.display_name
    db.session.delete(person)
    try:
        db.session.commit()
    except IntegrityError:
        # A person referenced by leave/ledger/duty/parade rows can't be hard-
        # deleted — foreign keys (ON) reject it. History is the source of truth
        # (TECH_PLAN.md:58); deactivating is the reversible alternative.
        db.session.rollback()
        flash(
            f"Can't delete {name} — they're still referenced by leave, ledger, "
            "or duty history. Deactivate them instead (uncheck Active).",
            "error",
        )
        return redirect(url_for("admin.person_edit", person_id=person.id))
    flash(f"Deleted {name}.", "success")
    return redirect(url_for("admin.people"))


@bp.route("/people/<int:person_id>/reset-password", methods=["POST"])
@require(policy.can_manage_people)
def person_reset_password(person_id):
    person = db.session.get(Person, person_id) or abort(404)
    temp_password = _issue_temp_password(person)
    db.session.commit()
    flash(
        f"Temporary password for {person.display_name}: {temp_password} "
        "(shown once — they must change it at first login).",
        "success",
    )
    return redirect(url_for("admin.person_edit", person_id=person.id))


def _issue_temp_password(person):
    # Readable enough to relay over text; forced change makes it short-lived.
    temp_password = secrets.token_urlsafe(9)
    person.set_password(temp_password)
    person.must_change_pw = True
    return temp_password
