"""P2.8: clash panel wiring. Covers event_service.clashes_for's participant
precision, the ARCTIC visibility split, the 12:00 boundary (decision f)
end-to-end, and the submission flash / detail-panel surfaces built on top.
"""
from datetime import date, datetime

from app.domain.types import (
    Appointment,
    Calendar,
    DayPart,
    LeaveType,
    ParticipantCategory,
    Rank,
    RequestStatus,
    Service,
)
from app.extensions import db
from app.models import Event, EventParticipant, LeaveRequest, Person
from tests.conftest import login


def person_id_of(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def create_event(
    app,
    owner_id,
    *,
    calendar=Calendar.TP,
    title="Conduct",
    start=datetime(2026, 7, 6, 8, 0),
    end=datetime(2026, 7, 6, 17, 0),
    person_ids=None,
    category=None,
):
    with app.app_context():
        event = Event(calendar=calendar, title=title, start_dt=start, end_dt=end, created_by_id=owner_id)
        db.session.add(event)
        db.session.flush()
        if category is not None:
            db.session.add(EventParticipant(event_id=event.id, category=category, include=True))
        for pid in person_ids or []:
            db.session.add(EventParticipant(event_id=event.id, person_id=pid, include=True))
        db.session.commit()
        return event.id


def plant_request(
    app, person_id, start, end, *, day_part=DayPart.FULL, status=RequestStatus.PENDING_PC, type_=LeaveType.OFF,
):
    with app.app_context():
        req = LeaveRequest(
            person_id=person_id, type=type_, start_date=start, end_date=end,
            day_part=day_part, status=status,
        )
        db.session.add(req)
        db.session.commit()
        return req.id


def plant_leave(app, person_id, day, status=RequestStatus.APPROVED):
    with app.app_context():
        db.session.add(
            LeaveRequest(
                person_id=person_id, type=LeaveType.OFF, start_date=day, end_date=day,
                day_part=DayPart.FULL, status=status,
            )
        )
        db.session.commit()


def submit(client, start, end, type_="OFF", day_part="FULL"):
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


# ---------- Criterion 1: warn-only — flash fires, routing is untouched ----------

def test_clash_flash_warns_but_request_routes_same_as_no_clash(app, client, make_person):
    make_person(username="cp_opr1", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    opr_id = person_id_of(app, "cp_opr1")
    create_event(app, opr_id, title="Field camp", person_ids=[opr_id],
                 start=datetime(2026, 7, 6, 8, 0), end=datetime(2026, 7, 6, 17, 0))
    login(client, "cp_opr1")

    clashing = submit(client, date(2026, 7, 6), date(2026, 7, 6))
    assert b"tagged in 1 conduct" in clashing.data
    assert b"Field camp" in clashing.data

    clean = submit(client, date(2026, 7, 7), date(2026, 7, 7))
    assert b"tagged in" not in clean.data

    with app.app_context():
        statuses = [
            r.status
            for r in db.session.query(LeaveRequest)
            .filter_by(person_id=opr_id)
            .order_by(LeaveRequest.id)
            .all()
        ]
        assert len(statuses) == 2
        assert statuses[0] is RequestStatus.PENDING_PC
        assert statuses[1] is RequestStatus.PENDING_PC


# ---------- Criterion 2: PC and OC both see the conduct in the detail panel ----------

def test_pc_and_oc_both_see_conduct_in_detail_panel(app, client, make_person):
    make_person(username="cp_opr2", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    opr_id = person_id_of(app, "cp_opr2")
    create_event(app, opr_id, title="Range day", person_ids=[opr_id],
                 start=datetime(2026, 7, 6, 8, 0), end=datetime(2026, 7, 6, 17, 0))
    req_id = plant_request(app, opr_id, date(2026, 7, 6), date(2026, 7, 6))

    login(client, make_person(username="cp_pc2", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1))
    resp = client.get(f"/leave/{req_id}")
    assert b"Range day" in resp.data
    client.post("/logout")

    login(client, make_person(username="cp_oc2", rank=Rank.CPT, appointment=Appointment.OC, platoon=None))
    resp = client.get(f"/leave/{req_id}")
    assert b"Range day" in resp.data


# ---------- Criterion 3: ARCTIC visibility follows the viewer, not the requester ----------

def test_arctic_clash_hidden_from_opr_but_visible_to_command_team(app, client, make_person):
    make_person(username="cp_opr3", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    opr_id = person_id_of(app, "cp_opr3")
    create_event(app, opr_id, calendar=Calendar.ARCTIC, title="Arctic recce", person_ids=[opr_id],
                 start=datetime(2026, 7, 6, 8, 0), end=datetime(2026, 7, 6, 17, 0))
    login(client, "cp_opr3")

    resp = submit(client, date(2026, 7, 6), date(2026, 7, 6))
    assert b"Arctic recce" not in resp.data
    assert b"tagged in" not in resp.data

    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).filter_by(person_id=opr_id).scalar()

    resp = client.get(f"/leave/{req_id}")
    assert b"Arctic recce" not in resp.data
    client.post("/logout")

    login(client, make_person(username="cp_pc3", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1))
    resp = client.get(f"/leave/{req_id}")
    assert b"Arctic recce" in resp.data


# ---------- Criterion 4: decision-f boundary end-to-end (AM off vs afternoon conduct) ----------

def test_am_off_vs_afternoon_conduct_is_no_clash_end_to_end(app, client, make_person):
    make_person(username="cp_opr4", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    opr_id = person_id_of(app, "cp_opr4")
    create_event(app, opr_id, title="Afternoon drill", person_ids=[opr_id],
                 start=datetime(2026, 7, 6, 14, 0), end=datetime(2026, 7, 6, 17, 0))
    login(client, "cp_opr4")

    resp = submit(client, date(2026, 7, 6), date(2026, 7, 6), day_part="AM")
    assert b"tagged in" not in resp.data

    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).filter_by(person_id=opr_id).scalar()
    resp = client.get(f"/leave/{req_id}")
    assert b"Afternoon drill" not in resp.data


# ---------- Criterion 5: participant precision — untagged requester sees nothing ----------

def test_event_tagged_to_a_different_platoon_produces_no_clash(app, client, make_person):
    make_person(username="cp_opr5", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    opr_id = person_id_of(app, "cp_opr5")
    create_event(app, opr_id, title="Platoon 2 op", category=ParticipantCategory.PLATOON_2,
                 start=datetime(2026, 7, 6, 8, 0), end=datetime(2026, 7, 6, 17, 0))
    login(client, "cp_opr5")

    resp = submit(client, date(2026, 7, 6), date(2026, 7, 6))
    assert b"tagged in" not in resp.data

    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).filter_by(person_id=opr_id).scalar()
    resp = client.get(f"/leave/{req_id}")
    assert b"Platoon 2 op" not in resp.data


# ---------- Criterion 6: "already away" rows — distinct-person dedupe ----------

def test_already_away_rows_show_distinct_person_count_per_day(app, client, make_person):
    make_person(username="cp_requester6", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    requester_id = person_id_of(app, "cp_requester6")
    make_person(username="cp_other6", platoon=2)
    other_id = person_id_of(app, "cp_other6")
    # Two overlapping APPROVED requests for the same person, same day — must
    # still count as ONE person away (same rule as the P2.6 month cell).
    plant_leave(app, other_id, date(2026, 7, 7))
    plant_leave(app, other_id, date(2026, 7, 7))

    req_id = plant_request(app, requester_id, date(2026, 7, 6), date(2026, 7, 8))
    make_person(username="cp_viewer_oc6", rank=Rank.CPT, appointment=Appointment.OC, platoon=None)
    login(client, "cp_viewer_oc6")

    resp = client.get(f"/leave/{req_id}")
    # Already-away counts (distinct persons): only 7 Jul has someone away.
    assert resp.data.count(b"1 away") == 1
    assert resp.data.count(b"0 away") == 2
    # Fix 5: projected = already-away UNION the requester (one more person).
    assert resp.data.count(b"2 if approved") == 1  # 7 Jul: cp_other6 + requester
    assert resp.data.count(b"1 if approved") == 2  # 6 & 8 Jul: just the requester


# ---------- Fix 5: projected must not double-count an already-away requester ----------

def test_projected_does_not_double_count_requester_already_away(app, client, make_person):
    make_person(username="cp_req_nd", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    requester_id = person_id_of(app, "cp_req_nd")
    # The requester is ALREADY away on 9 Jul via a separate APPROVED leave.
    plant_leave(app, requester_id, date(2026, 7, 9))
    # ...and this pending request also covers 9 Jul.
    req_id = plant_request(app, requester_id, date(2026, 7, 9), date(2026, 7, 9))
    make_person(username="cp_viewer_oc_nd", rank=Rank.CPT, appointment=Appointment.OC, platoon=None)
    login(client, "cp_viewer_oc_nd")

    resp = client.get(f"/leave/{req_id}")
    # Requester is the only one away and approving adds no NEW person: projected == already.
    assert resp.data.count(b"1 away") == 1
    assert resp.data.count(b"1 if approved") == 1
    assert b"2 if approved" not in resp.data  # not double-counted
