"""The whole Phase 1 promise, exercised through HTTP only:
opening balance -> request -> PC endorse -> OC approve (one transaction) ->
balance changed -> morning parade shows the absence -> cancel -> everything
reversed.
"""
from datetime import date

from app.domain.types import Appointment, ParadeVariant, Rank
from app.extensions import db
from app.models import LeaveRequest, Person
from app.services import parade_service
from tests.conftest import login

FRI = date(2026, 7, 10)
MON = date(2026, 7, 13)


def _morning_absent(app, day):
    # The live morning page is today-only; an arbitrary covered day is asserted
    # through the same build_doc pipeline the page renders (page↔pipeline
    # equality is pinned by test_doc_builder).
    with app.app_context():
        return parade_service.build_doc(day, ParadeVariant.MORNING).text.split(
            "NOT PRESENT IN CAMP"
        )[1]


def test_core_loop_end_to_end(app, client, make_person):
    opr = make_person(username="e2e_opr", display_name="E2E Opr", platoon=1)
    pc = make_person(username="e2e_pc", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1)
    oc = make_person(username="e2e_oc", rank=Rank.CPT, appointment=Appointment.OC, platoon=None)
    s3 = make_person(
        username="e2e_s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
        company_role="S3", platoon=1,
    )
    with app.app_context():
        opr_id = db.session.query(Person.id).filter_by(username="e2e_opr").scalar()

    # S3 sets the opening balance through the UI: 3 days OFF.
    login(client, s3)
    client.post(
        f"/ledger/person/{opr_id}/adjust",
        data={"kind": "OFF", "direction": "add", "days": "3", "reason": "Opening balance"},
    )
    assert b"OFF: 3" in client.get(f"/ledger/person/{opr_id}").data
    client.post("/logout")

    # Opr requests Fri-Mon OFF (2 working days across a weekend).
    login(client, opr)
    client.post(
        "/leave/new",
        data={"type": "OFF", "start_date": FRI.isoformat(), "end_date": MON.isoformat(),
              "day_part": "FULL", "reason": "Family event"},
    )
    resp = client.get("/leave/")
    assert b"Pending PC" in resp.data
    client.post("/logout")

    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).limit(1).scalar()

    # PC sees it in the platoon queue, endorses.
    login(client, pc)
    assert b"E2E Opr" in client.get("/leave/queue/pc").data
    detail = client.get(f"/leave/{req_id}").data
    assert b"2 OFF deducted" in detail  # working-days breakdown visible pre-decision
    client.post(f"/leave/{req_id}/pc-approve")
    client.post("/logout")

    # OC approves — the one action that plots AND deducts.
    login(client, oc)
    assert b"E2E Opr" in client.get("/leave/queue/oc").data
    resp = client.post(f"/leave/{req_id}/oc-approve", follow_redirects=True)
    assert b"Approved" in resp.data
    client.post("/logout")

    # Balance moved 3 -> 1, visible to S3 with the request linked in history.
    login(client, s3)
    person_page = client.get(f"/ledger/person/{opr_id}").data
    assert b"OFF: 1" in person_page
    assert b"request" in person_page
    client.post("/logout")

    # The absence appears on the morning parade state for a covered day —
    # including the weekend inside the range — with no extra plotting step.
    # The document renders names uppercased (parade_line), and the absent
    # person lands under NOT PRESENT IN CAMP, never CURRENT STRENGTH.
    login(client, opr)
    assert "PTE E2E OPR" in _morning_absent(app, FRI)
    assert "PTE E2E OPR" in _morning_absent(app, date(2026, 7, 11))
    balances = client.get("/leave/").data
    assert b"OFF: 1" in balances
    client.post("/logout")

    # S3 cancels the approved leave: credit written, absence unplotted.
    login(client, s3)
    resp = client.post(f"/leave/{req_id}/cancel-approved", follow_redirects=True)
    assert b"reversed" in resp.data
    assert b"OFF: 3" in client.get(f"/ledger/person/{opr_id}").data
    # No longer absent: the person is back present, off the NOT-PRESENT list.
    assert "PTE E2E OPR" not in _morning_absent(app, FRI)
