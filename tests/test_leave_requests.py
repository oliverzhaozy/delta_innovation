from datetime import date

import pytest

from app.domain import routing
from app.domain.types import Appointment, Rank, RequestStatus
from app.extensions import db
from app.models import LeaveRequest, Person
from tests.conftest import login

WED = date(2026, 7, 8)
THU = date(2026, 7, 9)


def submit(client, start=WED, end=WED, type_="OFF", day_part="FULL"):
    return client.post(
        "/leave/new",
        data={
            "type": type_,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "day_part": day_part,
            "reason": "",
        },
        follow_redirects=True,
    )


def request_status(app, username):
    with app.app_context():
        return (
            db.session.query(LeaveRequest.status)
            .join(Person, LeaveRequest.person_id == Person.id)
            .filter(Person.username == username)
            .scalar()
        )


def test_initial_status_by_appointment():
    assert routing.initial_status(Appointment.OPR) is RequestStatus.PENDING_PC
    assert routing.initial_status(Appointment.DET_COMD) is RequestStatus.PENDING_PC
    assert routing.initial_status(Appointment.PS) is RequestStatus.PENDING_PC
    assert routing.initial_status(Appointment.PC) is RequestStatus.PENDING_OC
    for regular in (Appointment.OC, Appointment.SM, Appointment.TWO_IC, Appointment.P2IC):
        with pytest.raises(ValueError):
            routing.initial_status(regular)


def test_opr_request_starts_pending_pc(app, client, make_person):
    login(client, make_person(username="opr_req"))
    resp = submit(client)
    assert b"Request submitted." in resp.data
    assert request_status(app, "opr_req") is RequestStatus.PENDING_PC


def test_pc_request_skips_to_oc(app, client, make_person):
    login(client, make_person(username="pc_req", rank=Rank.TWO_LT, appointment=Appointment.PC))
    submit(client)
    assert request_status(app, "pc_req") is RequestStatus.PENDING_OC


def test_regular_is_outside_the_flow(client, make_person):
    login(client, make_person(username="p2ic_req", rank=Rank.SSG, appointment=Appointment.P2IC))
    assert client.get("/leave/new").status_code == 403
    assert client.get("/leave/").status_code == 403


def test_half_day_must_be_single_day(client, make_person):
    login(client, make_person(username="opr_half"))
    resp = submit(client, start=WED, end=THU, day_part="AM")
    assert b"must be a single day" in resp.data


def test_end_before_start_rejected(client, make_person):
    login(client, make_person(username="opr_rev"))
    resp = submit(client, start=THU, end=WED)
    assert b"before start date" in resp.data


def test_overlap_warns_but_submits(app, client, make_person):
    login(client, make_person(username="opr_dup"))
    submit(client)
    resp = submit(client)
    assert b"overlaps your existing request" in resp.data
    with app.app_context():
        assert db.session.query(LeaveRequest).count() == 2


def test_cancel_own_pending(app, client, make_person):
    login(client, make_person(username="opr_cxl"))
    submit(client)
    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).scalar()
    resp = client.post(f"/leave/{req_id}/cancel", follow_redirects=True)
    assert b"Request cancelled." in resp.data
    with app.app_context():
        assert db.session.get(LeaveRequest, req_id).status is RequestStatus.CANCELLED


def test_cannot_cancel_someone_elses_request(app, client, make_person):
    login(client, make_person(username="opr_victim"))
    submit(client)
    client.post("/logout")
    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).scalar()
    login(client, make_person(username="opr_attacker"))
    assert client.post(f"/leave/{req_id}/cancel").status_code == 403
