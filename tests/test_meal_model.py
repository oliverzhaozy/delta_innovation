"""P3b.5 — MealAdjustment model. S4's manual per-meal ± must survive recompiles
(it cannot be a form one-shot), so it is a persisted, append-only row: corrections
are compensating adjustments, never edits or deletes (ledger philosophy).
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import Meal
from app.extensions import db
from app.models import MealAdjustment, Person

DAY = date(2026, 7, 6)


def person_id_of(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def test_reason_not_null_enforced_in_db(app, make_person):
    # reason is mandatory: an unexplained ± to a food order is the exact thing
    # this column exists to prevent.
    make_person(username="meal_noreason")
    with app.app_context():
        pid = person_id_of(app, "meal_noreason")
        row = MealAdjustment(
            date=DAY, meal=Meal.BREAKFAST, delta=2, reason=None, created_by_id=pid
        )
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_meal_adjustment_persists_with_defaults(app, make_person):
    make_person(username="meal_ok")
    with app.app_context():
        pid = person_id_of(app, "meal_ok")
        row = MealAdjustment(
            date=DAY, meal=Meal.DINNER, delta=-3, reason="Two guests dropped out",
            created_by_id=pid,
        )
        db.session.add(row)
        db.session.commit()  # should not raise
        assert row.id is not None
        assert row.created_at is not None      # created_at default now_sgt
        assert row.delta == -3                 # negative delta is legal (± people)


def test_append_only_allows_repeat_rows_for_same_date_and_meal(app, make_person):
    # No unique(date, meal): a correction is a second (compensating) row, and
    # the two rows together ARE the audit trail — mirrors ledger/snapshot posture.
    make_person(username="meal_repeat")
    with app.app_context():
        pid = person_id_of(app, "meal_repeat")
        db.session.add(MealAdjustment(
            date=DAY, meal=Meal.LUNCH, delta=5, reason="Extra visitors", created_by_id=pid))
        db.session.add(MealAdjustment(
            date=DAY, meal=Meal.LUNCH, delta=-5, reason="Correction: visitors cancelled",
            created_by_id=pid))
        db.session.commit()  # should not raise
        rows = db.session.query(MealAdjustment).filter_by(date=DAY, meal=Meal.LUNCH).all()
        assert len(rows) == 2
        assert sum(r.delta for r in rows) == 0  # net effect of the pair


def test_meal_stored_as_value_not_python_name(app, make_person):
    make_person(username="meal_enumval")
    with app.app_context():
        pid = person_id_of(app, "meal_enumval")
        row = MealAdjustment(
            date=DAY, meal=Meal.BREAKFAST, delta=1, reason="One late add-on",
            created_by_id=pid)
        db.session.add(row)
        db.session.commit()
        stored = db.session.execute(
            db.text("SELECT meal FROM meal_adjustment WHERE id = :id"), {"id": row.id}
        ).scalar()
        assert stored == "BREAKFAST"  # values_callable stores .value, not TWO_LT-style name
