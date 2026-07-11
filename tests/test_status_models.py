from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import DayPart, DirectAbsenceType, STATUS_IN_CAMP_DEFAULT, StatusType
from app.extensions import db
from app.models import DirectAbsence, Person, StatusEntry

TODAY = date(2026, 8, 3)
TOMORROW = TODAY + timedelta(days=1)


def person_id_of(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


# --- enums -------------------------------------------------------------

def test_status_type_enum_members_and_labels():
    # BRIEFING and SITE_TESTING were removed UI-21 (owner directive 2026-07-11);
    # a briefing/site-testing is keyed as OTHER with the reason in remarks.
    assert [t.value for t in StatusType] == ["MC", "COURSE", "OTHER"]
    assert StatusType.MC.label == "MC"
    assert StatusType.COURSE.label == "On course"
    assert StatusType.OTHER.label == "Other"


def test_direct_absence_type_enum_members_and_labels():
    assert [t.value for t in DirectAbsenceType] == ["LEAVE", "OTHER"]
    assert DirectAbsenceType.LEAVE.label == "Leave"
    assert DirectAbsenceType.OTHER.label == "Other"


def test_status_in_camp_default_pinned_and_total():
    assert STATUS_IN_CAMP_DEFAULT == {
        StatusType.MC: False,
        StatusType.COURSE: False,
        StatusType.OTHER: False,
    }
    # Totality: every enum member must have a default, so a new member
    # without one breaks this test rather than silently defaulting.
    assert set(STATUS_IN_CAMP_DEFAULT) == set(StatusType)


# --- StatusEntry ---------------------------------------------------------

def test_status_entry_date_order_check_constraint_enforced_in_db(app, make_person):
    make_person(username="status_dbcheck")
    with app.app_context():
        pid = person_id_of(app, "status_dbcheck")
        row = StatusEntry(
            person_id=pid,
            type=StatusType.MC,
            start_date=TODAY + timedelta(days=2),
            end_date=TODAY + timedelta(days=1),
            in_camp=False,
            created_by_id=pid,
        )
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_status_entry_half_day_spanning_multiple_days_rejected(app, make_person):
    make_person(username="status_halfday")
    with app.app_context():
        pid = person_id_of(app, "status_halfday")
        row = StatusEntry(
            person_id=pid,
            type=StatusType.OTHER,
            start_date=TODAY,
            end_date=TOMORROW,
            day_part=DayPart.AM,
            in_camp=True,
            created_by_id=pid,
        )
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_status_entry_half_day_single_day_accepted(app, make_person):
    make_person(username="status_halfday_ok")
    with app.app_context():
        pid = person_id_of(app, "status_halfday_ok")
        row = StatusEntry(
            person_id=pid,
            type=StatusType.OTHER,
            start_date=TODAY,
            end_date=TODAY,
            day_part=DayPart.PM,
            in_camp=True,
            created_by_id=pid,
        )
        db.session.add(row)
        db.session.commit()  # should not raise
        assert row.id is not None


def test_status_entry_full_multi_day_accepted(app, make_person):
    make_person(username="status_multiday_ok")
    with app.app_context():
        pid = person_id_of(app, "status_multiday_ok")
        row = StatusEntry(
            person_id=pid,
            type=StatusType.MC,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=3),
            in_camp=False,
            created_by_id=pid,
        )
        db.session.add(row)
        db.session.commit()  # should not raise
        assert row.day_part is DayPart.FULL  # column default


# --- DirectAbsence -------------------------------------------------------

def test_direct_absence_date_order_check_constraint_enforced_in_db(app, make_person):
    make_person(username="direct_dbcheck")
    with app.app_context():
        pid = person_id_of(app, "direct_dbcheck")
        row = DirectAbsence(
            person_id=pid,
            type=DirectAbsenceType.LEAVE,
            start_date=TODAY + timedelta(days=2),
            end_date=TODAY + timedelta(days=1),
            created_by_id=pid,
        )
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_direct_absence_half_day_spanning_multiple_days_rejected(app, make_person):
    make_person(username="direct_halfday")
    with app.app_context():
        pid = person_id_of(app, "direct_halfday")
        row = DirectAbsence(
            person_id=pid,
            type=DirectAbsenceType.OTHER,
            start_date=TODAY,
            end_date=TOMORROW,
            day_part=DayPart.AM,
            created_by_id=pid,
        )
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_direct_absence_half_day_single_day_accepted(app, make_person):
    make_person(username="direct_halfday_ok")
    with app.app_context():
        pid = person_id_of(app, "direct_halfday_ok")
        row = DirectAbsence(
            person_id=pid,
            type=DirectAbsenceType.LEAVE,
            start_date=TODAY,
            end_date=TODAY,
            day_part=DayPart.AM,
            created_by_id=pid,
        )
        db.session.add(row)
        db.session.commit()  # should not raise
        assert row.id is not None


def test_direct_absence_full_multi_day_accepted(app, make_person):
    make_person(username="direct_multiday_ok")
    with app.app_context():
        pid = person_id_of(app, "direct_multiday_ok")
        row = DirectAbsence(
            person_id=pid,
            type=DirectAbsenceType.LEAVE,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=5),
            created_by_id=pid,
        )
        db.session.add(row)
        db.session.commit()  # should not raise
        assert row.day_part is DayPart.FULL


def test_direct_absence_has_no_in_camp_column():
    """Pins the TECH_PLAN shape: a direct absence is out of camp by definition;
    in-camp exceptions are what status_entry's in_camp flag is for."""
    assert "in_camp" not in DirectAbsence.__table__.columns
    assert "in_camp" in StatusEntry.__table__.columns
