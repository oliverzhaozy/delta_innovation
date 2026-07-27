from datetime import date

from app.domain.types import (
    Appointment,
    BalanceKind,
    LedgerSource,
    Rank,
    RequestStatus,
    Service,
)
from app.extensions import db
from app.models import LedgerEntry, LeaveRequest, Person
from app.services import ledger_service
from tests.conftest import login

WED = date(2026, 7, 8)


def make_s3(make_person, username="s3"):
    return make_person(
        username=username, rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
        company_role="S3",
    )


def test_opr_cannot_see_ledger(client, make_person):
    login(client, make_person(username="opr_x"))
    assert client.get("/ledger/").status_code == 403


def test_balances_table_flags_negatives(app, client, make_person):
    make_person(username="deficit_guy")
    login(client, make_s3(make_person))
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="deficit_guy").scalar()
        s3_id = db.session.query(Person.id).filter_by(username="s3").scalar()
        ledger_service.post_entry(
            person_id=pid, kind=BalanceKind.OFF, delta_half_days=-3,
            reason="carried over deficit", source=LedgerSource.MANUAL, created_by_id=s3_id,
        )
        db.session.commit()
    resp = client.get("/ledger/")
    assert b"-1.5" in resp.data
    assert b'class="neg"' in resp.data


def test_ledger_index_is_parade_ordered_not_platoon_or_alphabetical(client, make_person):
    # UI-22: the balances table reads the shared active-roster fetch, so the PS
    # leads despite the Opr sitting in platoon 1 AND alphabetizing first (the
    # old platoon → name order led with her).
    make_person(username="led_zps", display_name="Zed Ps", rank=Rank.TWO_SG,
                appointment=Appointment.PS, platoon=3)
    make_person(username="led_aopr", display_name="Ann Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=1)
    login(client, make_s3(make_person))

    body = client.get("/ledger/").get_data(as_text=True)
    assert body.index("Zed Ps") < body.index("Ann Opr")


def test_ledger_index_lists_nsfs_only(client, make_person):
    # Regulars' off/leave lives in ARCTIC FOE (owner directive 2026-07-26), so
    # the balances table never lists them.
    make_person(username="led_nsf", display_name="Nsf Guy")
    make_person(username="led_reg", display_name="Reg Guy", rank=Rank.CPT,
                appointment=Appointment.OC, platoon=None, service=Service.REGULAR)
    login(client, make_s3(make_person))

    body = client.get("/ledger/").get_data(as_text=True)
    assert "Nsf Guy" in body
    assert "Reg Guy" not in body


def test_manual_adjustment_appears_in_history_and_balance(app, client, make_person):
    make_person(username="awardee")
    login(client, make_s3(make_person))
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="awardee").scalar()
    resp = client.post(
        f"/ledger/person/{pid}/adjust",
        data={"kind": "OIL", "direction": "add", "days": "1.5", "reason": "Exercise support"},
        follow_redirects=True,
    )
    assert b"Adjustment recorded." in resp.data
    assert b"Exercise support" in resp.data
    with app.app_context():
        assert ledger_service.balance(pid, BalanceKind.OIL) == 3


def test_quarter_day_rejected(app, client, make_person):
    make_person(username="qtr")
    login(client, make_s3(make_person))
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="qtr").scalar()
    resp = client.post(
        f"/ledger/person/{pid}/adjust",
        data={"kind": "OFF", "direction": "add", "days": "0.7", "reason": "x"},
    )
    assert b"whole or half days" in resp.data


def test_cancel_approved_reverses_ledger(app, client, make_person):
    """The P1.9 core: cancellation restores the balance via a REVERSAL row."""
    make_person(username="opr_c", platoon=1)
    make_person(username="pc1_c", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1)
    make_person(username="oc_c", rank=Rank.CPT, appointment=Appointment.OC, platoon=None)
    s3 = make_s3(make_person, username="s3_c")

    login(client, "opr_c")
    client.post(
        "/leave/new",
        data={"type": "OFF", "start_date": WED.isoformat(), "end_date": WED.isoformat(),
              "day_part": "FULL", "reason": ""},
    )
    client.post("/logout")
    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).limit(1).scalar()
        opr_id = db.session.query(Person.id).filter_by(username="opr_c").scalar()

    login(client, "pc1_c")
    client.post(f"/leave/{req_id}/pc-approve")
    client.post("/logout")
    login(client, "oc_c")
    client.post(f"/leave/{req_id}/oc-approve", data={"confirm_negative": "1"})
    client.post("/logout")

    with app.app_context():
        assert ledger_service.balance(opr_id, BalanceKind.OFF) == -2

    login(client, s3)
    resp = client.post(f"/leave/{req_id}/cancel-approved", follow_redirects=True)
    assert b"reversed" in resp.data
    with app.app_context():
        assert db.session.get(LeaveRequest, req_id).status is RequestStatus.CANCELLED
        assert ledger_service.balance(opr_id, BalanceKind.OFF) == 0
        rows = db.session.query(LedgerEntry).filter_by(leave_request_id=req_id).all()
        assert {r.source for r in rows} == {LedgerSource.LEAVE_APPROVAL, LedgerSource.REVERSAL}

    # Second cancel: already actioned, no double credit.
    resp = client.post(f"/leave/{req_id}/cancel-approved", follow_redirects=True)
    assert b"already actioned" in resp.data
    with app.app_context():
        assert ledger_service.balance(opr_id, BalanceKind.OFF) == 0


def test_requester_cannot_cancel_approved(app, client, make_person):
    make_person(username="opr_nc", platoon=1)
    login(client, "opr_nc")
    client.post(
        "/leave/new",
        data={"type": "LL", "start_date": WED.isoformat(), "end_date": WED.isoformat(),
              "day_part": "FULL", "reason": ""},
    )
    with app.app_context():
        req_id = db.session.query(LeaveRequest.id).limit(1).scalar()
        db.session.get(LeaveRequest, req_id).status = RequestStatus.APPROVED
        db.session.commit()
    assert client.post(f"/leave/{req_id}/cancel-approved").status_code == 403
    resp = client.post(f"/leave/{req_id}/cancel", follow_redirects=True)
    assert b"ask S3" in resp.data


def test_person_edit_lists_open_leave_items(app, client, make_person):
    make_person(username="opr_open", platoon=1)
    login(client, "opr_open")
    client.post(
        "/leave/new",
        data={"type": "OFF", "start_date": "2027-01-06", "end_date": "2027-01-06",
              "day_part": "FULL", "reason": ""},
    )
    client.post("/logout")
    login(client, make_s3(make_person, username="s3_open"))
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="opr_open").scalar()
    resp = client.get(f"/admin/people/{pid}")
    assert b"Open leave items" in resp.data
    assert b"Pending PC" in resp.data
