"""The Phase 2 promise, exercised through HTTP only — the P2.11 sibling of
test_e2e_core_loop.py: an ARCTIC event with category + except + also-include
participants -> a member's overlapping leave surfaces the clash to both PC
and OC (but never to the requester, who can't see ARCTIC) -> OC approves ->
S3 records an early return -> ledger, balances, and the away board all agree.
"""
from datetime import date

from app.domain.types import Appointment, Rank
from app.extensions import db
from app.models import Event, LeaveRequest, Person
from tests.conftest import login

# Tue-Wed-Thu, 1-3 Sep 2026: three consecutive working days, no weekend inside.
TUE = date(2026, 9, 1)
WED = date(2026, 9, 2)
THU = date(2026, 9, 3)


def test_phase2_end_to_end(app, client, make_person):
    requester = make_person(
        username="nh_requester", display_name="Nighthawk Requester", platoon=2,
    )
    x = make_person(username="nh_x", display_name="Nighthawk Excepted", platoon=2)
    y = make_person(username="nh_y", display_name="Nighthawk Included", platoon=1)
    pc2 = make_person(
        username="nh_pc2", display_name="2LT Nighthawk PC2",
        rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=2,
    )
    oc = make_person(
        username="nh_oc", display_name="CPT Nighthawk OC",
        rank=Rank.CPT, appointment=Appointment.OC, platoon=None,
    )
    s3 = make_person(
        username="nh_s3", display_name="2SG Nighthawk S3",
        rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
        company_role="S3", platoon=1,
    )
    with app.app_context():
        requester_id = db.session.query(Person.id).filter_by(username="nh_requester").scalar()
        x_id = db.session.query(Person.id).filter_by(username="nh_x").scalar()
        y_id = db.session.query(Person.id).filter_by(username="nh_y").scalar()

    # 1. S3 keys REQUESTER's opening OFF balance: 4 days, through the UI.
    login(client, s3)
    client.post(
        f"/ledger/person/{requester_id}/adjust",
        data={"kind": "OFF", "direction": "add", "days": "4", "reason": "Opening balance"},
    )
    assert b"OFF: 4" in client.get(f"/ledger/person/{requester_id}").data
    client.post("/logout")

    # 2. PC2 (command team) creates an ARCTIC event spanning the 3 working
    # days: "Platoon 2 except X plus Y" (category include, person except,
    # person also-include — P2.5's picker).
    login(client, pc2)
    resp = client.post(
        "/calendar/new",
        data={
            "calendar": "ARCTIC",
            "title": "Ex NIGHTHAWK",
            "start_dt": "2026-09-01T08:00",
            "end_dt": "2026-09-03T17:00",
            "notes": "",
            "categories": ["PLATOON_2"],
            "include_people": [str(y_id)],
            "except_people": [str(x_id)],
        },
        follow_redirects=True,
    )
    assert b"Event created" in resp.data
    with app.app_context():
        event_id = db.session.query(Event.id).filter_by(title="Ex NIGHTHAWK").scalar()
    client.post("/logout")

    # 3. REQUESTER (platoon 2, tagged via category — not command team) submits
    # OFF covering the whole event window. ARCTIC must stay invisible: no
    # mention of the event on the submission response, even though the
    # request does clash with it.
    login(client, requester)
    resp = client.post(
        "/leave/new",
        data={
            "type": "OFF", "start_date": TUE.isoformat(), "end_date": THU.isoformat(),
            "day_part": "FULL", "reason": "Ex NIGHTHAWK overlap",
        },
        follow_redirects=True,
    )
    assert b"Request submitted." in resp.data
    assert b"Ex NIGHTHAWK" not in resp.data
    assert b"Pending PC" in resp.data  # Opr routes PC -> OC (CLAUDE.md routing rule)
    client.post("/logout")

    with app.app_context():
        request_id = db.session.query(LeaveRequest.id).filter_by(person_id=requester_id).scalar()

    # 4. PC2 opens the request detail: the clash panel names the event
    # (command team can see ARCTIC). PC2 then endorses — required before the
    # OC can act at all, per the PC -> OC route.
    login(client, pc2)
    assert b"Ex NIGHTHAWK" in client.get(f"/leave/{request_id}").data
    resp = client.post(f"/leave/{request_id}/pc-approve", follow_redirects=True)
    assert b"Endorsed" in resp.data
    client.post("/logout")

    # OC opens the same request: same clash panel visible.
    login(client, oc)
    assert b"Ex NIGHTHAWK" in client.get(f"/leave/{request_id}").data

    # 5. OC approves — plots the absence and deducts in one transaction.
    # Opening balance (4 days) comfortably covers the 3-day cost, so the
    # confirm-negative flow never triggers.
    resp = client.post(f"/leave/{request_id}/oc-approve", follow_redirects=True)
    assert b"Approved" in resp.data
    client.post("/logout")

    login(client, s3)
    for d in (TUE, WED, THU):
        assert b"Nighthawk Requester" in client.get(f"/parade/away?date={d.isoformat()}").data
    # 3 working days x 2 half-days = 6 half-days deducted from the 8 opened.
    assert b"OFF: 1" in client.get(f"/ledger/person/{requester_id}").data

    # 6. S3 performs an early return to the first leave day (Tue): the
    # request shortens, and a compensating REVERSAL credits the 2 working
    # days no longer taken.
    resp = client.post(
        f"/leave/{request_id}/early-return",
        data={"new_end_date": TUE.isoformat()},
        follow_redirects=True,
    )
    assert b"Early return recorded" in resp.data

    assert b"Nighthawk Requester" in client.get(f"/parade/away?date={TUE.isoformat()}").data
    assert b"Nighthawk Requester" not in client.get(f"/parade/away?date={WED.isoformat()}").data
    assert b"Nighthawk Requester" not in client.get(f"/parade/away?date={THU.isoformat()}").data

    person_page = client.get(f"/ledger/person/{requester_id}").data
    # Balance = opening (4 days) - cost of the single remaining day (1 day) = 3.
    assert b"OFF: 3" in person_page
    assert b"Early return" in person_page  # the REVERSAL row's reason
    assert person_page.count(b"request") == 2  # debit row + reversal row, both linked
    client.post("/logout")

    # 7. Sanity: the resolved participants list (rank-prefixed rows, distinct
    # from the plain include/except chips above them) excludes X, includes Y.
    login(client, pc2)
    detail_page = client.get(f"/calendar/{event_id}").data
    assert b"PTE Nighthawk Excepted" not in detail_page
    assert b"PTE Nighthawk Included" in detail_page
    client.post("/logout")
