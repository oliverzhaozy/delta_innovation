"""P5.5 — /ro pages: view-for-all + command-team daily edits, S3-only standing
surfaces (boilerplate, standing timeline items, weekly key events).
"""
from datetime import date, timedelta

from app.domain.dates import today_sgt
from app.domain.types import Appointment, Rank, RoSection, Service
from app.extensions import db
from app.models import Person, RoDocument, RoExtraItem
from tests.conftest import login

FRI = date(2026, 6, 19)


def make_cast(make_person):
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    make_person(username="s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
                company_role="S3")


def test_ro_page_defaults_to_tomorrow(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")
    tomorrow = today_sgt() + timedelta(days=1)
    html = client.get("/ro").get_data(as_text=True)
    # The RO, like the COS message, is compiled the evening before.
    assert f"Routine Orders for {tomorrow.strftime('%d%m%y')}" in html


def test_opr_views_without_forms_and_mutations_403(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")

    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "Routine Orders for 190626" in html
    assert "<textarea" not in html
    assert "No confirmed duty" in html  # chrome reports the missing duties

    for path in ("/ro/messages", "/ro/extra/add", "/ro/extra/remove"):
        assert client.post(path, data={"date": FRI.isoformat()}).status_code == 403, path
    for path in ("/ro/boilerplate", "/ro/key-events", "/ro/standing"):
        assert client.get(path).status_code == 403, path


def test_command_team_edits_messages_and_extra_items(app, client, make_person):
    make_cast(make_person)
    login(client, "ps2")
    day = FRI.isoformat()

    resp = client.post("/ro/messages", data={"date": day, "messages": "QOTD test line"},
                       follow_redirects=True)
    assert "QOTD test line" in resp.get_data(as_text=True)

    resp = client.post(
        "/ro/extra/add",
        data={"date": day, "time": "18:00", "text": "Report to site"},
        follow_redirects=True,
    )
    assert "1800H\n- Report to site" in resp.get_data(as_text=True)

    resp = client.post(
        "/ro/extra/add", data={"date": day, "time": "", "text": "SBA"},
        follow_redirects=True,
    )
    assert "TBC\n- SBA" in resp.get_data(as_text=True)

    with app.app_context():
        item_id = db.session.query(RoExtraItem.id).filter_by(text="SBA").scalar()
    resp = client.post(
        "/ro/extra/remove", data={"date": day, "item_id": str(item_id)},
        follow_redirects=True,
    )
    assert "SBA" not in resp.get_data(as_text=True)


def test_boilerplate_page_is_s3_only_and_feeds_the_document(app, client, make_person):
    make_cast(make_person)
    # A PS is command team (daily edits) but NOT S3: standing text is staff work.
    login(client, "ps2")
    assert client.get("/ro/boilerplate").status_code == 403

    client.post("/logout")  # /login short-circuits for an authenticated session
    login(client, "s3")
    resp = client.post(
        "/ro/boilerplate",
        data={"section": RoSection.SAFETY.value, "content": "- Stay safe."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "Safety Matters\n- Stay safe." in html


def test_standing_items_page_add_remove(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")

    resp = client.post(
        "/ro/standing",
        data={"time": "06:00", "text": "Roll call & Breakfast",
              "recurrence": "DAILY", "position": "10"},
        follow_redirects=True,
    )
    assert "Roll call &amp; Breakfast" in resp.get_data(as_text=True)
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "0600H\n- Roll call &amp; Breakfast" in html or "0600H\n- Roll call & Breakfast" in html

    with app.app_context():
        from app.models import RoStandingItem
        item_id = db.session.query(RoStandingItem.id).scalar()
    client.post("/ro/standing/remove", data={"item_id": str(item_id)},
                follow_redirects=True)
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    # The 0600H block is gone from the document (nav chrome still says
    # "Roll call" for the parade page, so probe the timeline slot instead).
    assert "0600H" not in html


def test_key_events_page_feeds_the_week(app, client, make_person):
    make_cast(make_person)
    login(client, "s3")

    resp = client.post(
        "/ro/key-events",
        data={"week": FRI.isoformat(), "mon": "Wolf PT", "tue": "", "wed": "",
              "thu": "", "fri": "IPPT"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "Mon - Wolf PT" in html
    assert "Fri - IPPT" in html
