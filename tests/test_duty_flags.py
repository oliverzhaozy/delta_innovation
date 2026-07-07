"""P4.9 — warn-only, derived-at-render clash surfaces for leave-vs-duty.

Nothing is stored and nothing is blocked: the leave detail page lists the
requester's CONFIRMED duties in range, the roster page flags absent holders
(A8: the predicate is presence.resolve, NOT a leave-table join — an MC or a
direct absence flags exactly like leave), and roll call names the absent
holder in chrome. The PS resolves via manual replace or swap; approval is
never blocked and nobody is auto-reassigned.
"""
from datetime import date

from app.domain.types import (
    Appointment, DayPart, Duty, DutyState, LeaveType, Rank, RequestStatus,
    Service, StatusType,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, Person, StatusEntry
from app.services import duty_service
from tests.conftest import login

WED = date(2026, 8, 5)
THU = date(2026, 8, 6)
AUG = "2026-08"


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def make_cast(make_person):
    """Requester Opr + their PC (platoon 1) + the OC."""
    make_person(username="opr1", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    make_person(username="pc1", rank=Rank.LTA, appointment=Appointment.PC)
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR)


def plant_request(app, username, start=WED, end=THU, *,
                  status=RequestStatus.PENDING_OC):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = LeaveRequest(
            person_id=person_id, type=LeaveType.OFF, start_date=start,
            end_date=end, day_part=DayPart.FULL, status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def plant_duty(app, username, day, *, duty=Duty.COS, state=DutyState.CONFIRMED):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = DutyAssignment(
            date=day, duty=duty, person_id=person_id, state=state,
            created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# --- leave-detail duty panel (Task 1, B1) --------------------------------------------

def test_leave_detail_shows_confirmed_duties_in_range(app, client, make_person):
    make_cast(make_person)
    req_id = plant_request(app, "opr1")
    plant_duty(app, "opr1", WED)
    plant_duty(app, "opr1", THU, duty=Duty.CDOS, state=DutyState.PROPOSED)

    for viewer in ("opr1", "pc1", "oc"):
        login(client, viewer)
        html = client.get(f"/leave/{req_id}").get_data(as_text=True)
        assert "Confirmed duties on these dates" in html, viewer
        assert "COS — confirmed" in html, viewer
        # The PROPOSED CDO/S draft is not real and must not appear.
        assert html.count("— confirmed") == 1, viewer
        client.post("/logout")


def test_leave_detail_no_duties_message(app, client, make_person):
    make_cast(make_person)
    req_id = plant_request(app, "opr1")
    login(client, "opr1")

    html = client.get(f"/leave/{req_id}").get_data(as_text=True)
    assert "No confirmed duties on these dates." in html
