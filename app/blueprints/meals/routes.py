from datetime import date, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.authz import require
from app.blueprints.meals import bp
from app.blueprints.meals.forms import MealAdjustmentForm
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import Meal
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
    # Viewing is S4/admin-only too (unlike the parade pages): a food order is
    # S4's working tool, not broadcast information.
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
        history=meal_service.adjustment_rows(day),
        form=MealAdjustmentForm(),
    )


@bp.route("/adjust", methods=["POST"])
@require(policy.can_manage_meals)
def adjust():
    day = _parse_day(request.form.get("date", ""))
    form = MealAdjustmentForm()
    if form.validate_on_submit():
        meal_service.add_adjustment(
            day, Meal(form.meal.data), form.delta.data, form.reason.data.strip(), current_user
        )
        flash("Adjustment recorded.", "success")
    else:
        flash("Could not record — check the meal, amount, and reason.", "error")
    return redirect(url_for("meals.index", date=day.isoformat()))
