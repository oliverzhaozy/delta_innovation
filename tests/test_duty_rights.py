"""P4.8 — rotating COS keying rights. The pure predicate takes the duty fact
as a keyword-only, no-default parameter (A5: a default lets a missed call site
silently degrade to fallback-only rights; keyword-only-no-default makes a
stale caller TypeError in the suite). The DB-aware wrapper
duty_service.can_key_parade_today is what routes and templates call.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import Appointment, CompanyRole, Duty, Rank
from app.extensions import db
from app.models import DutyAssignment, Person
from app.services import duty_service
from tests.conftest import login


def _person(appointment, *, company_role=None, is_admin=False):
    return SimpleNamespace(
        appointment=appointment, company_role=company_role, is_admin=is_admin
    )


# --- pure predicates (policy.py stays DB-free) --------------------------------------

def test_can_key_parade_requires_duty_fact():
    # A5 pin: positional or missing -> TypeError, never a silent default.
    with pytest.raises(TypeError):
        policy.can_key_parade(_person(Appointment.PS))
    with pytest.raises(TypeError):
        policy.can_key_parade(_person(Appointment.PS), True)


def test_can_key_parade_matrix():
    assert policy.can_key_parade(_person(Appointment.PS), is_cos_of_day=False)
    assert policy.can_key_parade(
        _person(Appointment.OPR, company_role=CompanyRole.S3), is_cos_of_day=False
    )
    assert policy.can_key_parade(_person(Appointment.OPR, is_admin=True), is_cos_of_day=False)
    assert not policy.can_key_parade(_person(Appointment.OPR), is_cos_of_day=False)
    # The duty fact grants, never revokes.
    assert policy.can_key_parade(_person(Appointment.OPR), is_cos_of_day=True)


def test_can_edit_ro():
    with pytest.raises(TypeError):
        policy.can_edit_ro(_person(Appointment.OPR), True)
    assert policy.can_edit_ro(_person(Appointment.OPR), is_cdos_of_day=True)
    assert not policy.can_edit_ro(_person(Appointment.OPR), is_cdos_of_day=False)
    # A9's fallback: the command team can always edit the RO.
    assert policy.can_edit_ro(_person(Appointment.OC), is_cdos_of_day=False)


# --- the DB-aware wrapper and the routed rights -------------------------------------

def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def make_opr(make_person, username="opr1"):
    return make_person(username=username, rank=Rank.THREE_SG, appointment=Appointment.OPR)


def plant_cos(app, username, day, *, duty=Duty.COS):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = DutyAssignment(
            date=day, duty=duty, person_id=person_id, created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def keying_status(client):
    """A routed probe of `@require(duty_service.can_key_parade_today)`: the
    override reset on today's morning document. Granted -> 302 back to the page
    (resetting nothing when nothing was dragged), refused -> 403. The MC page is
    no longer a probe — it is self-service and carries no keying gate at all.
    """
    return client.post(
        "/parade/override/reset", data={"variant": "morning"}
    ).status_code


def test_cos_today_can_key(app, client, make_person):
    make_opr(make_person)
    plant_cos(app, "opr1", today_sgt())
    login(client, "opr1")

    with app.app_context():
        person = db.session.query(Person).filter_by(username="opr1").one()
        assert duty_service.can_key_parade_today(person) is True
    assert keying_status(client) == 302


def test_tomorrows_cos_can_key_today(app, client, make_person):
    # Tomorrow's COS compiles day-D's message on the evening of D−1.
    make_opr(make_person)
    plant_cos(app, "opr1", today_sgt() + timedelta(days=1))
    login(client, "opr1")

    assert keying_status(client) == 302


def test_deposed_or_expired_cos_loses_rights(app, client, make_person):
    make_opr(make_person)
    row_id = plant_cos(app, "opr1", today_sgt() - timedelta(days=1))
    login(client, "opr1")
    # Yesterday's COS gets nothing.
    assert keying_status(client) == 403

    row_id = plant_cos(app, "opr1", today_sgt())
    assert keying_status(client) == 302
    with app.app_context():
        db.session.delete(db.session.get(DutyAssignment, row_id))
        db.session.commit()
    # Deposed: the rights disappear with the assignment.
    assert keying_status(client) == 403


def test_cdos_gets_no_parade_keying(app, client, make_person):
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.P2IC, platoon=2)
    plant_cos(app, "ps2", today_sgt(), duty=Duty.CDOS)
    login(client, "ps2")
    # CDO/S edits the RO (P5) — different duty, different surface.
    assert keying_status(client) == 403


def test_cos_of_day_and_cdos_of_day(app, make_person):
    make_opr(make_person)
    with app.app_context():
        day = today_sgt()
        assert duty_service.cos_of_day(day) is None
        assert duty_service.cdos_of_day(day) is None
    plant_cos(app, "opr1", today_sgt())
    with app.app_context():
        assert duty_service.cos_of_day(today_sgt()).id == pid(app, "opr1")
        assert duty_service.cdos_of_day(today_sgt()) is None
