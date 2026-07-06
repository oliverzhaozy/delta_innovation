"""P3b.3 — COS message + roll call pages: view + finalize.

Both pages mirror the morning parade page's wiring (presence_inputs ->
compute -> render) and P3a.8's finalize/snapshot flow; see
test_morning_parade_page.py and test_snapshots.py for the sibling coverage
this file intentionally repeats for the two new documents. The conflicts
panel markup is duplicated from morning.html rather than extracted into a
shared partial (task decision: only extract if it doesn't touch the morning
page's rendered output; duplicating ~10 lines is the lower-risk option).
"""
from datetime import date, timedelta

from app.domain import parade as parade_domain
from app.domain.dates import today_sgt
from app.domain.types import (
    Appointment,
    DayPart,
    LeaveType,
    ParadeVariant,
    Rank,
    RequestStatus,
    Service,
)
from app.extensions import db
from app.models import LeaveRequest, ParadeSnapshot, Person
from app.services import parade_service, presence_service
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


def _live_cos_text(app, day, cos_person_id):
    # Independent recompute through the exact same pipeline the app itself
    # uses, so "byte-identical" is checked against a second derivation.
    with app.app_context():
        cos_person = db.session.get(Person, cos_person_id)
        pairs = presence_service.presence_inputs(day)
        doc = parade_domain.compute_cos_message(day, cos_person, pairs)
        return parade_domain.render_cos(doc)


def _live_roll_call_text(app, day):
    with app.app_context():
        pairs = presence_service.presence_inputs(day)
        doc = parade_domain.categorize(day, pairs, "roll_call")
        return parade_domain.render_roll_call(doc)


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


# --- done-criterion 4: finalize stores server-recomputed text; snapshots ----

def test_cos_message_finalize_stores_text_and_variant_with_selected_cos(app, client, make_person):
    make_person(username="ps_keyer", appointment=Appointment.PS, display_name="3SG Percy Sim")
    make_person(username="other_cos2", display_name="CPT Oscar Ong", rank=Rank.CPT)
    login(client, "ps_keyer")
    other_id = pid(app, "other_cos2")

    cos_page = client.get(f"/parade/cos-message?date={DAY.isoformat()}&cos={other_id}")
    assert b'action="/parade/cos-message/finalize"' in cos_page.data

    expected = _live_cos_text(app, DAY, other_id)
    resp = client.post(
        "/parade/cos-message/finalize",
        data={"date": DAY.isoformat(), "cos": str(other_id)},
    )
    assert resp.status_code == 302

    with app.app_context():
        snap = db.session.query(ParadeSnapshot).one()
        assert snap.rendered_text == expected
        assert snap.variant is ParadeVariant.COS_MESSAGE
        assert "CPT OSCAR ONG is the COS" in snap.rendered_text
        snap_id = snap.id

    assert resp.headers["Location"].endswith(f"/parade/snapshots/{snap_id}")


def test_roll_call_finalize_stores_text_and_variant(app, client, make_person):
    make_person(username="ps_keyer2", appointment=Appointment.PS)
    login(client, "ps_keyer2")

    page = client.get(f"/parade/roll-call?date={DAY.isoformat()}")
    assert b'action="/parade/roll-call/finalize"' in page.data

    expected = _live_roll_call_text(app, DAY)
    resp = client.post("/parade/roll-call/finalize", data={"date": DAY.isoformat()})
    assert resp.status_code == 302

    with app.app_context():
        snap = db.session.query(ParadeSnapshot).one()
        assert snap.rendered_text == expected
        assert snap.variant is ParadeVariant.ROLL_CALL
        snap_id = snap.id
    assert resp.headers["Location"].endswith(f"/parade/snapshots/{snap_id}")


def test_both_variants_appear_in_snapshots_newest_first(app, client, make_person):
    make_person(username="ps_keyer3", appointment=Appointment.PS)
    login(client, "ps_keyer3")

    client.post("/parade/cos-message/finalize", data={"date": DAY.isoformat()})
    client.post("/parade/roll-call/finalize", data={"date": DAY.isoformat()})

    with app.app_context():
        rows = parade_service.snapshots()
        assert len(rows) == 2
        newest, oldest = rows[0], rows[1]
        assert newest.variant is ParadeVariant.ROLL_CALL
        assert oldest.variant is ParadeVariant.COS_MESSAGE
        newest_id, oldest_id = newest.id, oldest.id

    listing = client.get("/parade/snapshots")
    assert listing.status_code == 200
    # Table cells specifically — the nav bar itself now also says "COS message".
    assert listing.data.count(b"<td>COS message</td>") == 1
    assert listing.data.count(b"<td>Roll call state</td>") == 1
    newest_pos = listing.data.find(f"/parade/snapshots/{newest_id}".encode())
    oldest_pos = listing.data.find(f"/parade/snapshots/{oldest_id}".encode())
    assert newest_pos != -1 and oldest_pos != -1
    assert newest_pos < oldest_pos  # newest first


def test_cos_finalize_tamper_ignored_server_recomputes(app, client, make_person):
    make_person(username="ps_keyer5", appointment=Appointment.PS, display_name="3SG Percy Sim")
    login(client, "ps_keyer5")
    own_id = pid(app, "ps_keyer5")

    # An invalid cos id in the POST itself must ALSO fall back to current_user
    # — the finalize route re-validates, it never trusts the hidden field blindly.
    expected = _live_cos_text(app, DAY, own_id)
    resp = client.post(
        "/parade/cos-message/finalize",
        data={"date": DAY.isoformat(), "cos": "999999", "rendered_text": "HACKED"},
    )
    assert resp.status_code == 302
    with app.app_context():
        snap = db.session.query(ParadeSnapshot).one()
        assert snap.rendered_text == expected
        assert "HACKED" not in snap.rendered_text
        assert snap.variant is ParadeVariant.COS_MESSAGE


def test_roll_call_finalize_tamper_ignored_server_recomputes(app, client, make_person):
    make_person(username="ps_keyer6", appointment=Appointment.PS)
    login(client, "ps_keyer6")

    expected = _live_roll_call_text(app, DAY)
    resp = client.post(
        "/parade/roll-call/finalize",
        data={"date": DAY.isoformat(), "rendered_text": "HACKED", "variant": "MORNING"},
    )
    assert resp.status_code == 302
    with app.app_context():
        snap = db.session.query(ParadeSnapshot).one()
        assert snap.rendered_text == expected
        assert "HACKED" not in snap.rendered_text
        assert snap.variant is ParadeVariant.ROLL_CALL


# --- done-criterion 5: RBAC — Opr views, 403s on finalize; keyer succeeds ---

def test_opr_views_both_pages_but_403_on_finalize_keyer_succeeds(app, make_person):
    make_person(username="opr_viewer", appointment=Appointment.OPR)
    make_person(username="ps_keyer4", appointment=Appointment.PS)

    opr_client = app.test_client()
    login(opr_client, "opr_viewer")

    cos_page = opr_client.get(f"/parade/cos-message?date={DAY.isoformat()}")
    assert cos_page.status_code == 200
    assert b'action="/parade/cos-message/finalize"' not in cos_page.data

    roll_page = opr_client.get(f"/parade/roll-call?date={DAY.isoformat()}")
    assert roll_page.status_code == 200
    assert b'action="/parade/roll-call/finalize"' not in roll_page.data

    cos_forbidden = opr_client.post("/parade/cos-message/finalize", data={"date": DAY.isoformat()})
    assert cos_forbidden.status_code == 403

    roll_forbidden = opr_client.post("/parade/roll-call/finalize", data={"date": DAY.isoformat()})
    assert roll_forbidden.status_code == 403

    ps_client = app.test_client()
    login(ps_client, "ps_keyer4")
    ok = ps_client.post("/parade/cos-message/finalize", data={"date": DAY.isoformat()})
    assert ok.status_code == 302
    ok2 = ps_client.post("/parade/roll-call/finalize", data={"date": DAY.isoformat()})
    assert ok2.status_code == 302

    with app.app_context():
        assert db.session.query(ParadeSnapshot).count() == 2  # the 403s appended nothing


# --- nav: both links visible to every logged-in user ------------------------

def test_nav_shows_cos_message_and_roll_call_links_to_every_logged_in_user(client, make_person):
    login(client, make_person(username="anyviewer2", appointment=Appointment.OPR))
    home = client.get("/").data
    assert b'href="/parade/cos-message"' in home
    assert b'href="/parade/roll-call"' in home
