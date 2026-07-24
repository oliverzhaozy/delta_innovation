"""P4.1 — duty_assignment model.

One holder per (date, duty) — the UNIQUE constraint is the data-corruption
backstop (two COS on one night is not a judgment call).
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import Duty, DutyState
from app.extensions import db
from app.models import DutyAssignment, Person

DAY = date(2026, 8, 3)  # a Monday


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def test_duty_assignment_persists_with_defaults(app, make_person):
    make_person(username="duty_guy")
    with app.app_context():
        pid = _pid(app, "duty_guy")
        row = DutyAssignment(
            date=DAY, duty=Duty.COS, person_id=pid, state=DutyState.PROPOSED,
            created_by_id=pid,
        )
        db.session.add(row)
        db.session.commit()
        assert row.id is not None
        assert row.created_at is not None
        assert row.confirmed_by_id is None and row.confirmed_at is None  # draft
        assert row.person.username == "duty_guy"


def test_second_holder_for_same_date_and_duty_is_rejected(app, make_person):
    make_person(username="duty_a")
    make_person(username="duty_b", platoon=2)
    with app.app_context():
        pid_a, pid_b = _pid(app, "duty_a"), _pid(app, "duty_b")
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.COS, person_id=pid_a, state=DutyState.PROPOSED,
            created_by_id=pid_a))
        db.session.commit()
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.COS, person_id=pid_b, state=DutyState.PROPOSED,
            created_by_id=pid_a))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_same_date_different_duty_is_fine(app, make_person):
    make_person(username="duty_cos")
    make_person(username="duty_cdos", platoon=2)
    with app.app_context():
        pid_cos, pid_cdos = _pid(app, "duty_cos"), _pid(app, "duty_cdos")
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.COS, person_id=pid_cos, state=DutyState.PROPOSED,
            created_by_id=pid_cos))
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.CDOS, person_id=pid_cdos, state=DutyState.PROPOSED,
            created_by_id=pid_cos))
        db.session.commit()  # should not raise
        assert db.session.query(DutyAssignment).filter_by(date=DAY).count() == 2


def test_duty_stored_as_value_not_python_name(app, make_person):
    make_person(username="duty_enumval")
    with app.app_context():
        pid = _pid(app, "duty_enumval")
        row = DutyAssignment(
            date=DAY, duty=Duty.CDOS, person_id=pid, state=DutyState.CONFIRMED,
            created_by_id=pid)
        db.session.add(row)
        db.session.commit()
        stored_duty, stored_state = db.session.execute(
            db.text("SELECT duty, state FROM duty_assignment WHERE id = :id"),
            {"id": row.id},
        ).one()
        assert (stored_duty, stored_state) == ("CDOS", "CONFIRMED")


def test_duty_enum_members_and_labels():
    assert [d.value for d in Duty] == ["COS", "CDOS"]
    assert Duty.COS.label == "COS"
    assert Duty.CDOS.label == "CDO/S"
    assert [s.value for s in DutyState] == ["PROPOSED", "CONFIRMED"]
