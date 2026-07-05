import secrets

from flask import abort, flash, redirect, render_template, url_for

from app.authz import require
from app.blueprints.admin import bp
from app.blueprints.admin.forms import PersonForm
from app.domain import policy
from app.domain.types import Appointment, CompanyRole, Rank, Service
from app.extensions import db
from app.models import Person


def _apply_form(person, form):
    person.username = form.username.data.strip().lower()
    person.display_name = form.display_name.data.strip()
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
    everyone = (
        db.session.query(Person)
        .order_by(Person.is_active.desc(), Person.platoon.nulls_first(), Person.display_name)
        .all()
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
    return render_template("admin/person_form.html", form=form, person=person)


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
