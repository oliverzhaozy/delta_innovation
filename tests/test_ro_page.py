"""P5.5 — /ro pages: view-for-all + command-team daily edits, S3-only
boilerplate surface. Standing timeline items and the weekly key-events page
were removed 2026-07-24 (key events derive from the TP calendar).
"""
from datetime import date, datetime

from app.domain.dates import next_weekday, today_sgt
from app.domain.types import Appointment, Calendar, Rank, RoSection
from app.extensions import db
from app.models import Event, Person, RoExtraItem
from tests.conftest import login

THU = date(2026, 6, 18)
FRI = date(2026, 6, 19)
SAT = date(2026, 6, 20)
SUN = date(2026, 6, 21)
MON = date(2026, 6, 22)
TUE = date(2026, 6, 23)


def make_cast(make_person):
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    make_person(username="s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
                company_role="S3")


def test_ro_page_defaults_to_the_next_weekday(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")
    home = next_weekday(today_sgt())
    html = client.get("/ro").get_data(as_text=True)
    # The RO, like the COS message, is compiled the evening before — and only
    # ever for a weekday, so Fri/Sat/Sun default to the Monday.
    assert f"Routine Orders for {home.strftime('%d%m%y')}" in html


def test_opr_views_without_forms_and_mutations_403(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")

    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "Routine Orders for 190626" in html
    assert "<textarea" not in html
    assert "No confirmed duty" in html  # chrome reports the missing duties

    for path in ("/ro/messages", "/ro/extra/add", "/ro/extra/remove"):
        assert client.post(path, data={"date": FRI.isoformat()}).status_code == 403, path
    assert client.get("/ro/boilerplate").status_code == 403


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


def test_boilerplate_page_is_s3_or_admin_and_feeds_the_document(app, client, make_person):
    make_cast(make_person)
    # Standing text is staff work: S3's, or admin's — and command team is admin
    # by appointment since 2026-08-02, so the PS reaches it and an Opr does not.
    login(client, "opr1")
    assert client.get("/ro/boilerplate").status_code == 403
    client.post("/logout")  # /login short-circuits for an authenticated session

    login(client, "ps2")
    assert client.get("/ro/boilerplate").status_code == 200
    client.post("/logout")

    login(client, "s3")
    resp = client.post(
        "/ro/boilerplate",
        data={"section": RoSection.SAFETY.value, "content": "- Stay safe."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "Safety Matters\n- Stay safe." in html


def test_removed_standing_surfaces_are_gone(app, client, make_person):
    # 2026-07-24 revision: the standing-items and key-events pages no longer
    # exist for anyone — not even the S3 — and the view page drops their links.
    make_cast(make_person)
    login(client, "s3")
    for path in ("/ro/standing", "/ro/standing/remove", "/ro/key-events"):
        assert client.get(path).status_code == 404, path
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "Standing timeline items" not in html
    assert "Weekly key events" not in html


def test_warning_drops_the_tail_clause(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "No confirmed duty for this date" in html
    assert "confirm the roster" not in html


def test_day_nav_and_home_chip(app, client, monkeypatch, make_person):
    make_cast(make_person)
    login(client, "opr1")
    # Pin "today" to Fri 19 Jun 2026 so the home day is the Monday after it.
    monkeypatch.setattr("app.blueprints.ro.routes.today_sgt", lambda: FRI)

    html = client.get("/ro").get_data(as_text=True)
    assert "day-nav" in html
    assert "Back to" not in html  # the home day needs no way back

    html = client.get(f"/ro?date={THU.isoformat()}").get_data(as_text=True)
    assert f'href="/ro?date={MON.isoformat()}"' in html
    assert "Back to Monday" in html


def test_weekend_date_rolls_forward_to_monday(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")
    for weekend_day in (SAT, SUN):
        html = client.get(f"/ro?date={weekend_day.isoformat()}").get_data(as_text=True)
        assert MON.strftime("%A, %d %b %Y") in html, weekend_day
        assert "Routine Orders for 220626" in html, weekend_day
        assert f'href="/ro?date={FRI.isoformat()}"' in html, weekend_day
        assert f'href="/ro?date={TUE.isoformat()}"' in html, weekend_day


def test_day_nav_skips_weekends(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")

    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert f'href="/ro?date={MON.isoformat()}"' in html  # next
    assert f'href="/ro?date={THU.isoformat()}"' in html  # prev
    assert f'href="/ro?date={SAT.isoformat()}"' not in html

    html = client.get(f"/ro?date={MON.isoformat()}").get_data(as_text=True)
    assert f'href="/ro?date={FRI.isoformat()}"' in html  # prev
    assert f'href="/ro?date={SUN.isoformat()}"' not in html


def test_key_events_derive_from_tp_on_the_page(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")
    with app.app_context():
        s3_id = db.session.query(Person.id).filter_by(username="s3").scalar()
        db.session.add(Event(
            calendar=Calendar.TP, title="IPPT",
            start_dt=datetime(2026, 6, 19, 6, 45), end_dt=datetime(2026, 6, 19, 12, 0),
            created_by_id=s3_id,
        ))
        db.session.commit()
    html = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert "Fri - IPPT" in html
    assert "Mon - Garage Maintenance" in html
