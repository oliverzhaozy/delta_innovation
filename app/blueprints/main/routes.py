from flask import render_template
from flask_login import current_user, login_required

from app.blueprints.main import bp
from app.services import dashboard_service


@bp.route("/")
@login_required
def dashboard():
    # Home is the per-role to-do dashboard (UI-25): everything still open for
    # this person, re-derived on every request. The month calendar it replaced
    # lives on at calendar.month. The endpoint name stays `main.dashboard` so
    # every auth redirect (login_view, post-login, post-password-change) that
    # targets url_for("main.dashboard") is unchanged.
    return render_template(
        "main/dashboard.html",
        dash=dashboard_service.build_dashboard(current_user),
    )
