"""Dev-only user switcher. This blueprint is registered ONLY when
DEV_LOGIN_SWITCHER is on (DevConfig); in prod the endpoints don't exist and
ProdConfig.validate refuses the flag outright."""
from flask import abort, redirect, session, url_for
from flask_login import login_user

from app.blueprints.dev import bp
from app.extensions import db
from app.models import Person


@bp.app_context_processor
def inject_dev_switch_people():
    # base.html renders the switcher dropdown on every page (~36 rows, dev only).
    people = (
        db.session.query(Person)
        .filter_by(is_active=True)
        .order_by(Person.display_name)
        .all()
    )
    return {"dev_switch_people": people}


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
