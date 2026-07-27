"""P4.1 — duty_assignment + duty_blocked_day models.

One holder per (date, duty) — the UNIQUE constraint is the data-corruption
backstop (two COS on one night is not a judgment call) — and one block per
date, which is what lets the service insert-and-catch instead of pre-checking.
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import Duty
from app.extensions import db
from app.models import DutyAssignment, DutyBlockedDay, Person

DAY = date(2026, 8, 3)  # a Monday


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def test_duty_assignment_persists_with_defaults(app, make_person):
    make_person(username="duty_guy")
    with app.app_context():
        pid = _pid(app, "duty_guy")
        row = DutyAssignment(date=DAY, duty=Duty.COS, person_id=pid, created_by_id=pid)
        db.session.add(row)
        db.session.commit()
        assert row.id is not None
        assert row.created_at is not None
        assert row.is_manual is False  # the generator's default; assign() flips it
        assert row.person.username == "duty_guy"


def test_second_holder_for_same_date_and_duty_is_rejected(app, make_person):
    make_person(username="duty_a")
    make_person(username="duty_b", platoon=2)
    with app.app_context():
        pid_a, pid_b = _pid(app, "duty_a"), _pid(app, "duty_b")
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.COS, person_id=pid_a, created_by_id=pid_a))
        db.session.commit()
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.COS, person_id=pid_b, created_by_id=pid_a))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_same_date_different_duty_is_fine(app, make_person):
    make_person(username="duty_cos")
    make_person(username="duty_cdos", platoon=2)
    with app.app_context():
        pid_cos, pid_cdos = _pid(app, "duty_cos"), _pid(app, "duty_cdos")
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.COS, person_id=pid_cos, created_by_id=pid_cos))
        db.session.add(DutyAssignment(
            date=DAY, duty=Duty.CDOS, person_id=pid_cdos, created_by_id=pid_cos))
        db.session.commit()  # should not raise
        assert db.session.query(DutyAssignment).filter_by(date=DAY).count() == 2


def test_duty_stored_as_value_not_python_name(app, make_person):
    make_person(username="duty_enumval")
    with app.app_context():
        pid = _pid(app, "duty_enumval")
        row = DutyAssignment(
            date=DAY, duty=Duty.CDOS, person_id=pid, is_manual=True, created_by_id=pid)
        db.session.add(row)
        db.session.commit()
        stored_duty, stored_manual = db.session.execute(
            db.text("SELECT duty, is_manual FROM duty_assignment WHERE id = :id"),
            {"id": row.id},
        ).one()
        assert (stored_duty, stored_manual) == ("CDOS", 1)


def test_second_block_for_the_same_date_is_rejected(app, make_person):
    make_person(username="blocker")
    with app.app_context():
        pid = _pid(app, "blocker")
        db.session.add(DutyBlockedDay(date=DAY, created_by_id=pid))
        db.session.commit()
        db.session.add(DutyBlockedDay(date=DAY, created_by_id=pid))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        assert db.session.query(DutyBlockedDay).count() == 1


def test_duty_enum_members_and_labels():
    assert [d.value for d in Duty] == ["COS", "CDOS"]
    assert Duty.COS.label == "COS"
    assert Duty.CDOS.label == "CDO/S"
