from datetime import date, timedelta

from flask import render_template, request

from app.authz import require
from app.blueprints.meals import bp
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import Duty
from app.services import duty_service, meal_service


def _parse_day(raw: str) -> date:
    # Same fallback posture as the parade pages: a bad/missing ?date= renders
    # today rather than 400ing.
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return today_sgt()


@bp.route("")
@require(policy.can_manage_meals)
def index():
    # Viewing is S4/admin-only (unlike the parade pages): the indent numbers
    # are S4's working tool, not broadcast information.
    return render_template(
        "meals/index.html", **meal_service.month_context(request.args.get("ym", ""))
    )


@bp.route("/day")
@require(policy.can_manage_meals)
def day():
    day = _parse_day(request.args.get("date", ""))
    counts, imbalance = meal_service.compute_for(day)
    # Day D's overnight counter covers the night D → D+1 (one day LATER than
    # roll_call(D)'s night), so the notice reads the duty dated D.
    night_duties = {row.duty for row in duty_service.duties_on(day)}
    missing_duties = [duty for duty in Duty if duty not in night_duties]
    return render_template(
        "meals/day.html",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        back_ym="%04d-%02d" % (day.year, day.month),
        counts=counts,
        imbalance=imbalance,
        missing_duties=missing_duties,
    )
