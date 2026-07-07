"""P3b.6 — the meals page: /meals?date behind can_manage_meals (S4 or admin).

Counts are decision-support derived through parade_service.build_doc (the same
single pipeline the parade documents use — addendum A2), with S4's manual ±
recorded as append-only MealAdjustment rows: history, never edits. Done
criteria pinned here: Opr 403s; an adjustment changes the count AND appears in
history; the reason is mandatory.
"""
from datetime import date

from app.domain.types import CompanyRole, Meal
from app.extensions import db
from app.models import MealAdjustment
from tests.conftest import login

DAY = date(2026, 7, 8)  # Wednesday — same convention as the other parade tests


def _s4(make_person):
    return make_person(username="s4_guy", company_role=CompanyRole.S4, display_name="1SG Siti Rahim")


# --- access -------------------------------------------------------------------

def test_meals_page_403s_for_opr(app, client, make_person):
    make_person(username="opr1")
    login(client, "opr1")
    assert client.get(f"/meals?date={DAY.isoformat()}").status_code == 403
    assert client.post("/meals/adjust", data={"date": DAY.isoformat()}).status_code == 403


def test_meals_page_renders_counts_for_s4(app, client, make_person):
    _s4(make_person)
    make_person(username="stay_in", display_name="CFC Daniel Lim")
    login(client, "s4_guy")

    page = client.get(f"/meals?date={DAY.isoformat()}")
    assert page.status_code == 200
    # Two stay-in NSFs on the roster -> base 2 for all three meals.
    for label in (b"Breakfast", b"Lunch", b"Dinner"):
        assert label in page.data
    assert b"2" in page.data
    # The assumptions panel states the meal <-> category mapping in the open.
    assert b"roll call" in page.data.lower()


# --- adjustments: append-only, mandatory reason -------------------------------

def test_adjustment_changes_count_and_appears_in_history(app, client, make_person):
    _s4(make_person)
    make_person(username="stay_in")
    login(client, "s4_guy")

    resp = client.post(
        "/meals/adjust",
        data={
            "date": DAY.isoformat(),
            "meal": Meal.DINNER.value,
            "delta": "-1",
            "reason": "Advance party eats out",
        },
    )
    assert resp.status_code == 302

    with app.app_context():
        row = db.session.query(MealAdjustment).one()
        assert row.date == DAY
        assert row.meal is Meal.DINNER
        assert row.delta == -1
        assert row.created_by.username == "s4_guy"

    page = client.get(f"/meals?date={DAY.isoformat()}")
    assert b"Advance party eats out" in page.data  # history line
    # Base 2, adjustment -1 -> final 1 for dinner.
    assert b"1" in page.data


def test_adjustment_without_reason_is_rejected(app, client, make_person):
    _s4(make_person)
    login(client, "s4_guy")

    client.post(
        "/meals/adjust",
        data={"date": DAY.isoformat(), "meal": Meal.LUNCH.value, "delta": "3", "reason": ""},
    )
    with app.app_context():
        assert db.session.query(MealAdjustment).count() == 0


def test_zero_delta_adjustment_is_rejected(app, client, make_person):
    _s4(make_person)
    login(client, "s4_guy")

    client.post(
        "/meals/adjust",
        data={"date": DAY.isoformat(), "meal": Meal.LUNCH.value, "delta": "0", "reason": "noop"},
    )
    with app.app_context():
        assert db.session.query(MealAdjustment).count() == 0


def test_negative_final_is_flagged_not_clamped(app, client, make_person):
    _s4(make_person)
    login(client, "s4_guy")

    client.post(
        "/meals/adjust",
        data={"date": DAY.isoformat(), "meal": Meal.BREAKFAST.value, "delta": "-5", "reason": "typo"},
    )
    page = client.get(f"/meals?date={DAY.isoformat()}")
    # Base 1 (just the S4) - 5 = -4: shown as-is with the negative flag, never floored.
    assert b"-4" in page.data
    assert b"negative" in page.data.lower()
