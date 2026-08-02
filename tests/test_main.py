"""Home ("/") — the per-role to-do dashboard (UI-25). The month calendar it
replaced moved to /calendar/month and is covered by tests/test_month_view.py."""
from datetime import timedelta

from app.domain.dates import today_sgt
from app.domain.types import Appointment, DayPart, LeaveType, Rank, RequestStatus
from app.extensions import db
from app.models import LeaveRequest, Person
from tests.conftest import login

TODAY = today_sgt()


def plant_pending(app, username):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(LeaveRequest(
            person_id=person_id, type=LeaveType.OFF,
            start_date=TODAY + timedelta(days=2), end_date=TODAY + timedelta(days=2),
            day_part=DayPart.FULL, status=RequestStatus.PENDING_PC,
        ))
        db.session.commit()


def test_home_is_the_todo_dashboard(client, make_person):
    # Home is the dashboard, not the calendar: the Today panel is always there,
    # the month grid never is.
    username = make_person(username="opr_home", display_name="PTE Dash Test")
    login(client, username)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<h2>Today</h2>" in resp.data
    assert b"month-grid" not in resp.data
    # Nobody has keyed a duty, so the panel's stable shape shows its empties.
    assert b"none keyed" in resp.data


def test_approval_cards_are_role_gated(app, client, make_person):
    make_person(username="opr_pending", display_name="Ang Cheng Ze")
    plant_pending(app, "opr_pending")

    # The requester sees no approval card — a request is not their work.
    login(client, "opr_pending")
    body = client.get("/").data
    assert b"OFF/OIL/Leave approvals" not in body
    assert b"Nothing needs your action." in body
    client.post("/logout")

    # Their PC sees the card, naming them.
    make_person(username="pc_home", rank=Rank.LTA, appointment=Appointment.PC,
                display_name="Quek Jing Yu")
    login(client, "pc_home")
    body = client.get("/").data
    # Scoped to the card heading: the PC's nav renders the same counted label.
    assert b"<h2>OFF/OIL/Leave approvals (1)</h2>" in body
    assert b"Ang Cheng Ze" in body


def test_home_role_gating_lives_in_the_nav(client, make_person):
    # Role-gated access is via the nav, present on the dashboard home. A plain
    # Opr never sees the staff-only surfaces.
    login(client, make_person(username="opr_navcheck"))
    body = client.get("/").data
    assert b"OFF/OIL ledger" not in body
    client.post("/logout")

    s3 = make_person(
        username="s3_navcheck",
        rank=Rank.TWO_SG,
        appointment=Appointment.DET_COMD,
        company_role="S3",
    )
    login(client, s3)
    body = client.get("/").data
    assert b"OFF/OIL ledger" in body  # nav ledger link for S3
    assert b"ARCTIC FOE" not in body  # S3 Det Comd is not command team
