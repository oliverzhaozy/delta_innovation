"""P6.4/P6.6 — /manning pages: S3-only builder, flagged-not-hidden pick
lists, hard-blocked ineligible assignment, friendly duplicate error, document
render, and the two-way warn-only flags.
"""
import re
from datetime import date

from app.domain.types import (
    Appointment, DayPart, LeaveType, ManningSlotType, Rank, RequestStatus,
    Service,
)
from app.extensions import db
from app.models import LeaveRequest, ManningPeriod, ManningSlot, Person
from tests.conftest import login

START, END = date(2026, 7, 5), date(2026, 7, 13)


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def make_cast(make_person):
    make_person(username="s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
                company_role="S3", display_name="Dylan Chey")
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR, display_name="Wong Li Xuan")
    make_person(username="p2ic3", rank=Rank.THREE_WO, appointment=Appointment.P2IC,
                platoon=3, display_name="Wong Jingheng")
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Ang Cheng Ze")
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)


def create_period(client):
    return client.post("/manning/new", data={
        "start_date": START.isoformat(), "end_date": END.isoformat(),
    }, follow_redirects=True)


def period_id(app):
    with app.app_context():
        return db.session.query(ManningPeriod.id).scalar()


def test_manning_is_s3_only(app, client, make_person):
    make_cast(make_person)
    # A PS manages the duty roster but NOT manning (S3's surface).
    login(client, "ps2")
    assert client.get("/manning").status_code == 403
    assert client.post("/manning/new", data={}).status_code == 403
    assert client.post("/manning/1/generate", data={}).status_code == 403


def test_create_period_and_builder_renders_document(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    resp = create_period(client)
    html = resp.get_data(as_text=True)
    assert "TASK UNIT (TU) MANNING FOR" in html
    assert "050726 - 130726" in html
    # Unfilled HQ slots are chrome-reported from day one.
    assert "Unfilled: TU COMD, TU PLANNER" in html


def test_assign_renders_line_ineligible_400_duplicate_friendly(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)

    resp = client.post(f"/manning/{pid_}/assign", data={
        "slot": "TU_COMD", "person_id": str(pid(app, "oc")), "det_number": "",
    }, follow_redirects=True)
    assert "TU COMD: CPT WONG LI XUAN" in resp.get_data(as_text=True)

    # The trap, through the route: a company Det Comd into TU_DET_COMD -> 400.
    resp = client.post(f"/manning/{pid_}/assign", data={
        "slot": "TU_DET_COMD", "person_id": str(pid(app, "s3")), "det_number": "1",
    })
    assert resp.status_code == 400

    # Duplicate person -> friendly flash, not a 500.
    resp = client.post(f"/manning/{pid_}/assign", data={
        "slot": "TU_COMD", "person_id": str(pid(app, "oc")), "det_number": "",
    }, follow_redirects=True)
    assert "already in this period" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.query(ManningSlot).count() == 1


def test_tu_det_comd_pick_list_omits_company_det_comd(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    html = client.get(f"/manning/{period_id(app)}").get_data(as_text=True)

    select = re.search(
        r'data-slot="TU_DET_COMD".*?</select>', html, re.S
    ).group(0)
    assert "Wong Jingheng" in select          # P2IC: eligible
    assert "Dylan Chey" not in select         # company Det Comd: the trap
    personnel = re.search(r'data-slot="DET_PERSONNEL".*?</select>', html, re.S).group(0)
    assert "Dylan Chey" in personnel          # ...who fills Det Personnel


def test_remove_slot(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)
    with app.app_context():
        slot_id = db.session.query(ManningSlot.id).scalar()
    resp = client.post(f"/manning/{pid_}/remove", data={"slot_id": str(slot_id)},
                       follow_redirects=True)
    assert "ANG CHENG ZE" not in resp.get_data(as_text=True)


def test_generate_writes_rows_and_the_flash_carries_the_counts(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)
    # One manual pick first: it must survive, and it takes one det-1 personnel
    # slot off the open count.
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)

    resp = client.post(f"/manning/{pid_}/generate", data={})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/manning/{pid_}")

    # This cast has no PC at all and only two Det Personnel candidates, so the
    # counts say so out loud: 4 of the 9 slots still open could be filled.
    html = client.get(f"/manning/{pid_}").get_data(as_text=True)
    assert "Generated 4 of 9 open slots (keeps manual picks)." in html
    # The chip marks the S3's own pick, and ONLY that row.
    assert html.count('<span class="chip plain">manual</span>') == 1
    with app.app_context():
        rows = db.session.query(ManningSlot).filter_by(period_id=pid_).all()
        assert len(rows) == 5
        manual = [r for r in rows if r.is_manual]
        assert [r.person_id for r in manual] == [pid(app, "opr1")]


# --- two-way flags (P6.6) -----------------------------------------------------------

def plant_leave(app, username, start, end, *, status=RequestStatus.APPROVED):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = LeaveRequest(
            person_id=person_id, type=LeaveType.OFF, start_date=start,
            end_date=end, day_part=DayPart.FULL, status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def test_builder_flags_assigned_holder_derived_at_render(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)

    # The assigned-row flag renders as a badge — distinct from the pick-list
    # option text, which also carries reasons.
    flag_badge = 'badge rejected">&#9888; OFF 07 Jul – 08 Jul'

    # PENDING leave changes nothing (only APPROVED rows enter the fetch)...
    plant_leave(app, "opr1", date(2026, 7, 7), date(2026, 7, 8),
                status=RequestStatus.PENDING_PC)
    html = client.get(f"/manning/{pid_}").get_data(as_text=True)
    assert flag_badge not in html and "OFF 07 Jul" not in html

    # ...an APPROVED one flags the ASSIGNED row, derived at render.
    plant_leave(app, "opr1", date(2026, 7, 7), date(2026, 7, 8))
    html = client.get(f"/manning/{pid_}").get_data(as_text=True)
    assert flag_badge in html


def test_leave_detail_shows_manning_membership(app, client, make_person):
    make_cast(make_person)
    make_person(username="oc_appr", rank=Rank.CPT, appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)

    req_id = plant_leave(app, "opr1", date(2026, 7, 6), date(2026, 7, 7),
                         status=RequestStatus.PENDING_OC)
    client.post("/logout")
    login(client, "oc_appr")
    html = client.get(f"/leave/{req_id}").get_data(as_text=True)
    assert "Manning periods on these dates" in html
    assert "Det Personnel" in html
    assert "05 Jul – 13 Jul" in html

    # A request outside every period shows the empty state.
    req_id = plant_leave(app, "opr1", date(2026, 8, 3), date(2026, 8, 4),
                         status=RequestStatus.PENDING_OC)
    html = client.get(f"/leave/{req_id}").get_data(as_text=True)
    assert "No manning membership on these dates." in html


def test_admin_phone_field_round_trip(app, client, make_person):
    make_cast(make_person)
    make_person(username="admin", is_admin=True)
    client.post("/logout")
    login(client, "admin")
    oc_id = pid(app, "oc")
    page = client.get(f"/admin/people/{oc_id}").get_data(as_text=True)
    data = {
        "username": "oc", "display_name": "Wong Li Xuan", "phone": "9190 9702",
        "rank": "CPT", "appointment": "OC", "company_role": "", "platoon": "",
        "service": "REGULAR", "is_active": "y",
    }
    resp = client.post(f"/admin/people/{oc_id}", data=data, follow_redirects=True)
    assert b"Saved." in resp.data
    with app.app_context():
        assert db.session.get(Person, oc_id).phone == "9190 9702"
