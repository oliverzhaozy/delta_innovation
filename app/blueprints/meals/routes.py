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
    day = _parse_day(request.args.get("date", ""))
    counts, imbalance = meal_service.compute_for(day)
    return render_template(
        "meals/index.html",
        day=day,
        today=today_sgt(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        counts=counts,
        imbalance=imbalance,
    )
