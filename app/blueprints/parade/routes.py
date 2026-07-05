from datetime import date, timedelta

from flask import render_template, request
from flask_login import login_required

from app.blueprints.parade import bp
from app.domain.dates import today_sgt
from app.services import presence_service


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
