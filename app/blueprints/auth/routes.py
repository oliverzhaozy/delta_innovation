from urllib.parse import urlsplit

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.blueprints.auth import bp
from app.blueprints.auth.forms import ChangePasswordForm, LoginForm
from app.extensions import db, limiter
from app.models import Person


def _safe_next(default):
    # Only relative paths — an absolute ?next= would be an open redirect.
    target = request.args.get("next")
    if target and target.startswith("/") and not urlsplit(target).netloc:
        return target
    return default


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        person = (
            db.session.query(Person)
            .filter_by(username=form.username.data.strip().lower())
            .first()
        )
        # One generic message for unknown user, wrong password, or deactivated
        # account — the login page must not leak which usernames exist.
        if person is None or not person.check_password(form.password.data) or not person.is_active:
            flash("Invalid credentials.", "error")
        else:
            session.clear()  # rotate the session at the auth boundary (fixation)
            login_user(person, remember=form.remember.data)
            return redirect(_safe_next(url_for("main.dashboard")))
    return render_template("auth/login.html", form=form)


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
        else:
            current_user.set_password(form.new_password.data)
            current_user.must_change_pw = False
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/change_password.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    # Clear BEFORE logout_user(): logout_user() plants a '_remember': 'clear'
    # marker in the session that the after-request hook needs in order to
    # expire the remember-me cookie. Clearing afterwards wipes the marker and
    # remember-me users would be silently re-authenticated on their next request.
    session.clear()
    logout_user()
    return redirect(url_for("auth.login"))


@bp.before_app_request
def _force_password_change():
    # Seeded accounts start on a shared default password; nothing else in the
    # app is usable until the person sets their own.
    if (
        current_user.is_authenticated
        and current_user.must_change_pw
        and request.endpoint
        and request.endpoint not in {"auth.change_password", "auth.logout", "static"}
    ):
        return redirect(url_for("auth.change_password"))
