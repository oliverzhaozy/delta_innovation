"""Dev-only user switcher. This blueprint is registered ONLY when
DEV_LOGIN_SWITCHER is on (DevConfig); in prod the endpoints don't exist and
ProdConfig.validate refuses the flag outright."""
from flask import abort, redirect, session, url_for
from flask_login import current_user, login_user

from app.blueprints.dev import bp
from app.domain.parade import parade_sort_key
from app.extensions import db
from app.models import Person
from app.services import event_service


def _profile_key(person):
    # What testing cares about is the permission profile, not the individual:
    # appointment plus the orthogonal S3/S4 and admin grants. Names are noise.
    return (person.appointment, person.company_role, person.is_admin)


def _profile_label(person):
    extras = []
    if person.company_role is not None:
        extras.append(person.company_role.value)
    if person.is_admin:
        extras.append("admin")
    label = person.appointment.label
    return f"{label} ({', '.join(extras)})" if extras else label


@bp.app_context_processor
def inject_dev_switch_entries():
    # base.html renders the switcher dropdown on every page (dev only): one
    # entry per distinct profile, backed by an active holder. The shared roster
    # fetch arrives in parade order, so each profile's representative is its
    # senior-most holder and the entries themselves list appointment then rank.
    representatives = {}
    for person in event_service.active_roster():
        representatives.setdefault(_profile_key(person), person)
    current_key = _profile_key(current_user) if current_user.is_authenticated else None
    ordered = sorted(representatives.items(), key=lambda kv: parade_sort_key(kv[1]))
    return {
        "dev_switch_entries": [
            {"id": person.id, "label": _profile_label(person), "is_current": key == current_key}
            for key, person in ordered
        ]
    }


@bp.route("/switch/<int:person_id>", methods=["POST"])
def switch(person_id):
    # No @login_required: also usable from the login page.
    person = db.session.get(Person, person_id)
    if person is None or not person.is_active:
        abort(404)
    session.clear()  # rotate the session at the auth boundary (fixation)
    login_user(person)
    # Lets _force_password_change skip switched-in seeded accounts (which
    # default must_change_pw=True); the marker is inert unless the flag is on.
    session["dev_login_switch"] = True
    # Not the referring page — the new profile may not be allowed there.
    return redirect(url_for("main.dashboard"))
