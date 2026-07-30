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
        "service": "REGULAR",
    }
    resp = client.post(f"/admin/people/{oc_id}", data=data, follow_redirects=True)
    assert b"Saved." in resp.data
    with app.app_context():
        assert db.session.get(Person, oc_id).phone == "9190 9702"


# --- in-place editing surface + priority card ---------------------------------------

def slot_form(html, slot_id):
    """The reassign form belonging to one existing slot row."""
    inside = r"(?:(?!</form>).)*?"
    form = re.search(
        r'<form method="post" action="/manning/\d+/reassign" class="cell-assign">'
        + inside + r'name="slot_id" value="%d"' % slot_id
        + r"(?:(?!</form>).)*</form>",
        html, re.S,
    )
    assert form is not None, f"no reassign form for slot {slot_id}"
    return form.group(0)


def test_existing_rows_get_a_preselected_dropdown_and_open_positions_a_placeholder(
    app, client, make_person
):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)
    with app.app_context():
        slot_id = db.session.query(ManningSlot.id).scalar()

    html = client.get(f"/manning/{pid_}").get_data(as_text=True)
    form = slot_form(html, slot_id)
    # Reassign is a STATE edit, so the current holder is preselected.
    assert re.search(
        r'<option value="%d" selected>' % pid(app, "opr1"), form
    ) is not None
    # The four stacked "Assign <slot>" cards are gone; one compact escape hatch
    # for shapes the structure cannot express remains.
    assert "<h2>Assign Det Personnel (Det Comd/Opr)</h2>" not in html
    assert "<h2>Manual assignment</h2>" not in html
    assert "<h2>Add extra slot</h2>" in html
    # The structure's remaining positions each render their own placeholder line.
    assert html.count("— assign —") == 8   # 9 structural slots, one now filled
    assert "<em class=\"muted\">open</em>" in html


def test_reassign_swaps_the_holder_through_the_route(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)
    with app.app_context():
        slot_id = db.session.query(ManningSlot.id).scalar()

    resp = client.post(f"/manning/{pid_}/reassign", data={
        "slot_id": str(slot_id), "person_id": str(pid(app, "s3")),
    }, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "Reassigned." in html
    assert "DET PERSONNEL: 2SG DYLAN CHEY" in html   # the document followed
    with app.app_context():
        row = db.session.get(ManningSlot, slot_id)
        assert row.person_id == pid(app, "s3")
        assert row.is_manual is True


def test_reassign_ineligible_is_400_duplicate_flashes_foreign_slot_404s(
    app, client, make_person
):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "TU_DET_COMD", "person_id": str(pid(app, "p2ic3")), "det_number": "1",
    }, follow_redirects=True)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)
    client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "s3")), "det_number": "2",
    }, follow_redirects=True)
    with app.app_context():
        det_comd_id = db.session.query(ManningSlot.id).filter_by(
            slot=ManningSlotType.TU_DET_COMD).scalar()
        personnel_id = db.session.query(ManningSlot.id).filter_by(
            person_id=pid(app, "opr1")).scalar()
        second_id = db.session.query(ManningSlot.id).filter_by(
            person_id=pid(app, "s3")).scalar()

    # The trap: a company Det Comd into the DET COMD slot -> hard block.
    assert client.post(f"/manning/{pid_}/reassign", data={
        "slot_id": str(det_comd_id), "person_id": str(pid(app, "s3")),
    }).status_code == 400

    # Someone already in the period -> friendly flash, not a 500.
    resp = client.post(f"/manning/{pid_}/reassign", data={
        "slot_id": str(second_id), "person_id": str(pid(app, "opr1")),
    }, follow_redirects=True)
    assert "already in this period" in resp.get_data(as_text=True)

    # A slot from another period is not this URL's to edit.
    other = client.post("/manning/new", data={
        "start_date": "2026-09-01", "end_date": "2026-09-05",
    }, follow_redirects=True)
    assert other.status_code == 200
    with app.app_context():
        other_id = db.session.query(ManningPeriod.id).filter(
            ManningPeriod.id != pid_).scalar()
    assert client.post(f"/manning/{other_id}/reassign", data={
        "slot_id": str(personnel_id), "person_id": str(pid(app, "opr1")),
    }).status_code == 404

    with app.app_context():
        assert db.session.get(ManningSlot, personnel_id).person_id == pid(app, "opr1")


def test_reassign_is_s3_only(app, client, make_person):
    make_cast(make_person)
    login(client, "ps2")
    assert client.post("/manning/1/reassign", data={}).status_code == 403


def test_add_extra_slot_builds_a_det_outside_the_fixed_structure(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")
    create_period(client)
    pid_ = period_id(app)

    resp = client.post(f"/manning/{pid_}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "3",
    }, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "TU 3\nDET PERSONNEL: CPL ANG CHENG ZE" in html
    # Det 3 satisfies none of the fixed structure, so all nine lines stay open.
    assert html.count("— assign —") == 9


def test_priority_card_ranks_eligible_people_per_slot(app, client, make_person):
    make_cast(make_person)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Second Operator")
    login(client, "s3")
    # An earlier period opr1 served in; the builder being viewed is a later one.
    client.post("/manning/new", data={
        "start_date": "2026-05-04", "end_date": "2026-05-10",
    }, follow_redirects=True)
    old_id = period_id(app)
    client.post(f"/manning/{old_id}/assign", data={
        "slot": "DET_PERSONNEL", "person_id": str(pid(app, "opr1")), "det_number": "1",
    }, follow_redirects=True)
    create_period(client)
    with app.app_context():
        new_id = db.session.query(ManningPeriod.id).filter(
            ManningPeriod.id != old_id).scalar()

    html = client.get(f"/manning/{new_id}").get_data(as_text=True)
    card = re.search(
        r"<h3>Det Personnel \(Det Comd/Opr\) \(3\)</h3>.*?</ul>", html, re.S
    ).group(0)
    names = re.findall(r"<li><span>([^<]+)</span>", card)
    chips = re.findall(r'<span class="chip plain">([^<]+)</span>', card)
    # Never-served first (roster order), then the man whose period is behind him.
    assert names == ["2SG Dylan Chey", "CPL Second Operator", "CPL Ang Cheng Ze"]
    assert chips[:2] == ["never", "never"]
    assert chips[2].endswith("d ago") or chips[2].startswith("sched")
