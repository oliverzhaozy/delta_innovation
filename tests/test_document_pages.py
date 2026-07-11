"""P3b.3 — COS message + roll call pages: view + render.

Both pages mirror the morning parade page's wiring (presence_inputs ->
compute -> render); see test_morning_parade_page.py for the sibling coverage
this file intentionally repeats for the two new documents. The conflicts
panel markup is duplicated from morning.html rather than extracted into a
shared partial (task decision: only extract if it doesn't touch the morning
page's rendered output; duplicating ~10 lines is the lower-risk option).
"""
from datetime import date, timedelta

from app.domain.dates import today_sgt
from app.domain.types import (
    Appointment,
    DayPart,
    LeaveType,
    Rank,
    RequestStatus,
    Service,
)
from app.extensions import db
from app.models import LeaveRequest, Person
from tests.conftest import login

DAY = date(2026, 7, 8)  # Wednesday, matches test_morning_parade_page's convention


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def plant_leave(app, username, type_=LeaveType.OFF, status=RequestStatus.APPROVED,
                 day_part=DayPart.FULL, day=DAY):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            LeaveRequest(
                person_id=person_id, type=type_, start_date=day, end_date=day,
                day_part=day_part, status=status,
            )
        )
        db.session.commit()


# --- done-criterion 1: date defaults ----------------------------------------

def test_cos_message_defaults_to_tomorrow(client, make_person):
    login(client, make_person(username="viewer"))
    resp = client.get("/parade/cos-message")
    assert resp.status_code == 200
    tomorrow = today_sgt() + timedelta(days=1)
    assert tomorrow.strftime("%d%m%y").encode() in resp.data


def test_roll_call_defaults_to_today(client, make_person):
    login(client, make_person(username="viewer2"))
    resp = client.get("/parade/roll-call")
    assert resp.status_code == 200
    assert today_sgt().strftime("%d%m%y").encode() in resp.data


def test_bad_date_falls_back_to_convention_on_both_pages(client, make_person):
    login(client, make_person(username="viewer_bad_date"))
    assert client.get("/parade/cos-message?date=garbage").status_code == 200
    assert client.get("/parade/roll-call?date=garbage").status_code == 200


# --- done-criterion 2: COS selector ------------------------------------------

def test_cos_selector_defaults_to_current_user(client, make_person):
    login(client, make_person(username="viewer3", display_name="3SG Percy Sim",
                               rank=Rank.THREE_SG))
    resp = client.get(f"/parade/cos-message?date={DAY.isoformat()}")
    assert resp.status_code == 200
    assert b"3SG PERCY SIM is the COS" in resp.data


def test_cos_selector_query_param_selects_other_person(app, client, make_person):
    make_person(username="viewer4", display_name="3SG Percy Sim", rank=Rank.THREE_SG)
    make_person(username="other_cos", display_name="CPT Oscar Ong", rank=Rank.CPT)
    login(client, "viewer4")
    other_id = pid(app, "other_cos")
    resp = client.get(f"/parade/cos-message?date={DAY.isoformat()}&cos={other_id}")
    assert resp.status_code == 200
    assert b"CPT OSCAR ONG is the COS" in resp.data


def test_cos_selector_invalid_id_falls_back_to_current_user(client, make_person):
    login(client, make_person(username="viewer5", display_name="3SG Percy Sim",
                               rank=Rank.THREE_SG))
    resp = client.get(f"/parade/cos-message?date={DAY.isoformat()}&cos=999999")
    assert resp.status_code == 200
    assert b"3SG PERCY SIM is the COS" in resp.data

    resp2 = client.get(f"/parade/cos-message?date={DAY.isoformat()}&cos=garbage")
    assert resp2.status_code == 200
    assert b"3SG PERCY SIM is the COS" in resp2.data


def test_cos_selector_inactive_person_id_falls_back_to_current_user(app, client, make_person):
    login(client, make_person(username="viewer5b", display_name="3SG Percy Sim",
                               rank=Rank.THREE_SG))
    make_person(username="inactive_guy", display_name="CPL Ghost Guy", is_active=False)
    inactive_id = pid(app, "inactive_guy")

    resp = client.get(f"/parade/cos-message?date={DAY.isoformat()}&cos={inactive_id}")
    assert resp.status_code == 200
    assert b"3SG PERCY SIM is the COS" in resp.data
    assert b"GHOST GUY" not in resp.data


# --- done-criterion 3: planted data renders correctly on both ---------------

def test_cos_message_shows_regular_under_stay_out(client, make_person):
    login(client, make_person(username="viewer6", display_name="3SG Percy Sim",
                               rank=Rank.THREE_SG))
    make_person(username="reg_guy", display_name="CPT Oscar Ong", rank=Rank.CPT,
                service=Service.REGULAR)
    resp = client.get(f"/parade/cos-message?date={DAY.isoformat()}")
    assert resp.status_code == 200
    assert b"STAY OUT (1):\n1. CPT OSCAR ONG" in resp.data


def test_roll_call_shows_stay_out_nsf_and_pm_off_in_current_strength(app, client, make_person):
    make_person(username="viewer7", display_name="PTE Viewer Seven")
    make_person(username="stayout_nsf", display_name="3SG Ryan Tan", rank=Rank.THREE_SG,
                stay_out=True)
    make_person(username="pm_off_guy", display_name="PTE Aaron Goh")
    plant_leave(app, "pm_off_guy", type_=LeaveType.OFF, day_part=DayPart.PM)
    login(client, "viewer7")

    resp = client.get(f"/parade/roll-call?date={DAY.isoformat()}")
    assert resp.status_code == 200
    assert b"STAY OUT (1):\n1. 3SG RYAN TAN" in resp.data
    current_block = resp.data.split(b"PRESENT IN CAMP")[1].split(b"OTHERS IN CAMP")[0]
    assert b"PTE AARON GOH" in current_block


# --- done-criterion 4: any logged-in user views both document pages ---------

def test_opr_views_both_document_pages(app, make_person):
    # The documents are copy-only (there is no keyer-only action to gate), so
    # any logged-in user — down to a plain Opr — may view both.
    make_person(username="opr_viewer", appointment=Appointment.OPR)

    opr_client = app.test_client()
    login(opr_client, "opr_viewer")

    cos_page = opr_client.get(f"/parade/cos-message?date={DAY.isoformat()}")
    assert cos_page.status_code == 200

    roll_page = opr_client.get(f"/parade/roll-call?date={DAY.isoformat()}")
    assert roll_page.status_code == 200


# --- nav: both documents reachable by every logged-in user ------------------

def test_nav_reaches_cos_message_and_roll_call_for_every_logged_in_user(client, make_person):
    # UI refresh: the top nav now groups the parade pages behind the Parade
    # dropdown -> Parade state, and the three documents are URL-backed pills on
    # that page. The guarantee is unchanged (any logged-in user reaches both);
    # the path is Home -> Parade state -> pills.
    login(client, make_person(username="anyviewer2", appointment=Appointment.OPR))
    home = client.get("/", follow_redirects=True).data
    assert b'href="/parade/morning"' in home  # the Parade-state entry point
    pills = client.get("/parade/morning").data
    assert b'/parade/cos-message' in pills
    assert b'/parade/roll-call' in pills
