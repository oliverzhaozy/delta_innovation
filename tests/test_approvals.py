from datetime import date

import pytest

from app.domain.types import (
    Appointment,
    BalanceKind,
    LedgerSource,
    Rank,
    RequestStatus,
)
from app.extensions import db
from app.models import LedgerEntry, LeaveRequest, Person
from app.services import approval_service, ledger_service
from app.services.approval_service import TransitionError
from tests.conftest import login

FRI = date(2026, 7, 10)
MON = date(2026, 7, 13)
WED = date(2026, 7, 8)


@pytest.fixture()
def cast(app, make_person):
    """opr (P1), pc1, pc2, oc, s3 — the standing cast for approval tests."""
    make_person(username="opr", platoon=1)
    make_person(username="pc1", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1)
    make_person(username="pc2", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=2)
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC, platoon=None)
    make_person(
        username="s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
        company_role="S3", platoon=1,
    )
    with app.app_context():
        ids = dict(db.session.query(Person.username, Person.id).all())
    return ids


def submit_as(client, username, start=WED, end=WED, type_="OFF", day_part="FULL"):
    login(client, username)
    client.post(
        "/leave/new",
        data={
            "type": type_,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "day_part": day_part,
            "reason": "",
        },
    )
    client.post("/logout")


def latest_request_id(app):
    with app.app_context():
        return (
            db.session.query(LeaveRequest.id)
            .order_by(LeaveRequest.id.desc())
            .limit(1)
            .scalar()
        )


def give_off(app, cast, username, half_days):
    with app.app_context():
        ledger_service.post_entry(
            person_id=cast[username], kind=BalanceKind.OFF, delta_half_days=half_days,
            reason="opening balance", source=LedgerSource.MANUAL, created_by_id=cast["s3"],
        )
        db.session.commit()


def test_pc_queue_is_platoon_scoped(client, cast):
    submit_as(client, "opr")
    login(client, "pc1")
    assert b"Opr" in client.get("/leave/queue/pc").data
    client.post("/logout")
    login(client, "pc2")
    resp = client.get("/leave/queue/pc")
    assert b"Opr" not in resp.data
    # And PC2 cannot open the P1 request by URL either.
    assert client.get(f"/leave/{latest_request_id(client.application)}").status_code == 403


def test_full_chain_deducts_working_days_only(app, client, cast):
    give_off(app, cast, "opr", 6)  # 3 days
    submit_as(client, "opr", start=FRI, end=MON)  # Fri–Mon over a weekend = 2 working days

    login(client, "pc1")
    req_id = latest_request_id(app)
    client.post(f"/leave/{req_id}/pc-approve")
    client.post("/logout")

    login(client, "oc")
    resp = client.post(f"/leave/{req_id}/oc-approve", follow_redirects=True)
    assert b"Approved" in resp.data

    with app.app_context():
        row = db.session.get(LeaveRequest, req_id)
        assert row.status is RequestStatus.APPROVED
        assert row.pc_actor_id == cast["pc1"]
        assert row.oc_actor_id == cast["oc"]
        # 6 - (2 working days * 2 half-days) = 2
        assert ledger_service.balance(cast["opr"], BalanceKind.OFF) == 2
        entry = db.session.query(LedgerEntry).filter_by(leave_request_id=req_id).one()
        assert entry.source is LedgerSource.LEAVE_APPROVAL
        assert entry.delta_half_days == -4


def test_double_approval_deducts_once(app, client, cast):
    give_off(app, cast, "opr", 6)
    submit_as(client, "opr")
    req_id = latest_request_id(app)
    login(client, "pc1")
    client.post(f"/leave/{req_id}/pc-approve")
    client.post("/logout")
    login(client, "oc")
    client.post(f"/leave/{req_id}/oc-approve")
    resp = client.post(f"/leave/{req_id}/oc-approve", follow_redirects=True)
    assert b"already actioned" in resp.data
    with app.app_context():
        assert db.session.query(LedgerEntry).filter_by(leave_request_id=req_id).count() == 1


def test_negative_balance_requires_explicit_confirm(app, client, cast):
    submit_as(client, "opr")  # no opening balance: projected -1 day
    req_id = latest_request_id(app)
    login(client, "pc1")
    client.post(f"/leave/{req_id}/pc-approve")
    client.post("/logout")
    login(client, "oc")

    resp = client.post(f"/leave/{req_id}/oc-approve", follow_redirects=True)
    assert b"approve anyway" in resp.data
    with app.app_context():
        assert db.session.get(LeaveRequest, req_id).status is RequestStatus.PENDING_OC

    resp = client.post(
        f"/leave/{req_id}/oc-approve", data={"confirm_negative": "1"}, follow_redirects=True
    )
    assert b"Approved" in resp.data
    with app.app_context():
        assert ledger_service.balance(cast["opr"], BalanceKind.OFF) == -2


def test_same_day_part_double_count_is_hard_blocked(app, client, cast):
    give_off(app, cast, "opr", 8)
    # First: full-day Wed approved end-to-end.
    submit_as(client, "opr")
    first = latest_request_id(app)
    # Second: AM off the same Wed, endorsed to OC.
    submit_as(client, "opr", day_part="AM")
    second = latest_request_id(app)
    login(client, "pc1")
    client.post(f"/leave/{first}/pc-approve")
    client.post(f"/leave/{second}/pc-approve")
    client.post("/logout")
    login(client, "oc")
    client.post(f"/leave/{first}/oc-approve")
    resp = client.post(f"/leave/{second}/oc-approve", follow_redirects=True)
    assert b"double-count" in resp.data
    with app.app_context():
        assert db.session.get(LeaveRequest, second).status is RequestStatus.PENDING_OC


def test_ll_records_absence_without_ledger(app, client, cast):
    submit_as(client, "opr", type_="LL")
    req_id = latest_request_id(app)
    login(client, "pc1")
    client.post(f"/leave/{req_id}/pc-approve")
    client.post("/logout")
    login(client, "oc")
    client.post(f"/leave/{req_id}/oc-approve")
    with app.app_context():
        assert db.session.get(LeaveRequest, req_id).status is RequestStatus.APPROVED
        assert db.session.query(LedgerEntry).count() == 0


def test_rejection_requires_remark_and_records_it(app, client, cast):
    submit_as(client, "opr")
    req_id = latest_request_id(app)
    login(client, "pc1")
    resp = client.post(f"/leave/{req_id}/pc-reject", data={"remark": ""}, follow_redirects=True)
    assert b"remark is required" in resp.data
    client.post(f"/leave/{req_id}/pc-reject", data={"remark": "Exercise week"})
    with app.app_context():
        row = db.session.get(LeaveRequest, req_id)
        assert row.status is RequestStatus.REJECTED_PC
        assert row.remarks == "Exercise week"


def test_self_action_is_forbidden_in_the_service(app, cast):
    with app.app_context():
        req = LeaveRequest(
            person_id=cast["oc"], type="OFF", start_date=WED, end_date=WED,
            status=RequestStatus.PENDING_OC,
        )
        db.session.add(req)
        db.session.commit()
        actor = db.session.get(Person, cast["oc"])
        with pytest.raises(TransitionError, match="own request"):
            approval_service.oc_approve(req, actor)


def test_induced_failure_leaves_no_partial_state(app, client, cast, monkeypatch):
    give_off(app, cast, "opr", 6)
    submit_as(client, "opr")
    req_id = latest_request_id(app)
    login(client, "pc1")
    client.post(f"/leave/{req_id}/pc-approve")

    def boom(**kwargs):
        raise RuntimeError("induced mid-transaction failure")

    monkeypatch.setattr(approval_service.ledger_service, "post_entry", boom)
    with app.app_context():
        req = db.session.get(LeaveRequest, req_id)
        actor = db.session.query(Person).filter_by(username="oc").one()
        with pytest.raises(RuntimeError):
            approval_service.oc_approve(req, actor)
        db.session.expire_all()
        assert db.session.get(LeaveRequest, req_id).status is RequestStatus.PENDING_OC
        assert db.session.query(LedgerEntry).filter_by(leave_request_id=req_id).count() == 0
