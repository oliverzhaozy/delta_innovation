from flask import render_template, request
from flask_login import current_user, login_required

from app.blueprints.main import bp
from app.services import calendar_month


@bp.route("/")
@login_required
def dashboard():
    # Home IS the calendar (the "All Calendars" overlay). The endpoint name
    # stays `main.dashboard` so every auth redirect (login_view, post-login,
    # post-password-change) that targets url_for("main.dashboard") is unchanged.
    return render_template(
        "calendar/month.html",
        **calendar_month.build_month_context(current_user, request.args.get("ym", "")),
    )
