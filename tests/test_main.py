from app.domain.types import Appointment, Rank
from tests.conftest import login


def test_dashboard_shows_identity(client, make_person):
    username = make_person(username="opr_dash", display_name="PTE Dash Test")
    login(client, username)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"PTE Dash Test" in resp.data
    assert b"Platoon 1" in resp.data


def test_dashboard_content_is_role_aware(client, make_person):
    opr = make_person(username="opr_tools")
    login(client, opr)
    body = client.get("/").data
    assert b"My leave requests" in body  # UI refresh renamed the tile
    assert b"OFF/OIL ledger" not in body
    client.post("/logout")

    s3 = make_person(
        username="s3_tools",
        rank=Rank.TWO_SG,
        appointment=Appointment.DET_COMD,
        company_role="S3",
    )
    login(client, s3)
    body = client.get("/").data
    assert b"OFF/OIL ledger" in body
    assert b"ARCTIC FOE" not in body  # S3 Det Comd is not command team


def test_pc_sees_platoon_scoped_approvals_entry(client, make_person):
    pc = make_person(username="pc_tools", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=2)
    login(client, pc)
    body = client.get("/").data
    assert b"Platoon 2 approvals" in body
    assert b"ARCTIC FOE" in body  # PC is command team
