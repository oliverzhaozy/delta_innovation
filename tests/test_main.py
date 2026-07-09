from app.domain.types import Appointment, Rank
from tests.conftest import login


def test_home_is_the_calendar(client, make_person):
    # Home ("/") is now the month calendar overlay, not the old function tiles.
    username = make_person(username="opr_home", display_name="PTE Dash Test")
    login(client, username)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"month-grid" in resp.data
    # TP and NSF OFF/LEAVE toggles show for everyone.
    assert b'data-cal-toggle="tp"' in resp.data
    assert b'data-cal-toggle="off"' in resp.data


def test_home_arctic_layer_is_command_team_only(client, make_person):
    # A plain Opr: no ARCTIC toggle pill (and the server omits its chips too).
    login(client, make_person(username="opr_noarctic"))
    body = client.get("/").data
    assert b'data-cal-toggle="tp"' in body
    assert b'data-cal-toggle="arctic"' not in body
    client.post("/logout")

    # A PC is command team: the ARCTIC layer is available.
    pc = make_person(username="pc_arctic", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=2)
    login(client, pc)
    body = client.get("/").data
    assert b'data-cal-toggle="arctic"' in body


def test_home_role_gating_lives_in_the_nav(client, make_person):
    # The function tiles are gone; role-gated access is via the nav, present on
    # the calendar home. A plain Opr never sees the staff-only surfaces.
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
    assert b'data-cal-toggle="arctic"' not in body  # S3 Det Comd is not command team
