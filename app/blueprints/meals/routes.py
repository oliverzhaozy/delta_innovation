from datetime import date, timedelta

from flask import render_template, request

from app.authz import require
from app.blueprints.meals import bp
from app.domain import policy
from app.domain.dates import today_sgt
from app.services import meal_service


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
    expected, imbalance = meal_service.compute_for(day)
    return render_template(
        "meals/day.html",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        back_ym="%04d-%02d" % (day.year, day.month),
        expected=expected,
        imbalance=imbalance,
    )
