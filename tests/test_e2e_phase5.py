"""P5.6 — the Phase 5 end-to-end walk, via the test client only.

The whole stack reproduces the owner's normalized sample byte-for-byte: S3
confirms the duty roster for 19 Jun 2026 and keys the standing content
(boilerplate, standing timeline items, weekly key events); the CDO/CDS of the
date pastes the messages blob and keys the day's extra items; any viewer's
/ro page then renders EXACTLY the P5.3 golden. Then a TP conduct auto-inserts
and a removed extra item disappears — derived, never stored.
"""
import html as html_lib
import re
from datetime import date, datetime

from app.domain.types import Appointment, Calendar, Duty, Rank, RoSection
from app.extensions import db
from app.models import Event, Person
from tests.conftest import login
from tests.test_ro_domain import BOILERPLATE, GOLDEN, KEY_EVENTS, MESSAGES

FRI = date(2026, 6, 19)
MONTH = "2026-06"


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def _switch(client, username):
    client.post("/logout")
    login(client, username)


def _pre_text(page_html):
    match = re.search(r'<pre id="rotext"[^>]*>(.*?)</pre>', page_html, re.S)
    assert match, "the RO page must render the document <pre>"
    return html_lib.unescape(match.group(1))


def test_phase5_end_to_end(app, client, make_person):
    # --- Seed: S3 (admin, mirrors the real seed), the golden's duty pair ------
    make_person(username="s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
                company_role="S3", is_admin=True, display_name="Dylan Chey")
    make_person(username="quek", rank=Rank.LTA, appointment=Appointment.PC,
                platoon=1, display_name="Quek Jing Yu")
    make_person(username="ang", rank=Rank.CPL, appointment=Appointment.OPR,
                platoon=1, display_name="Ang Cheng Ze")

    # --- S3 assigns and confirms the date's duties through the roster UI ------
    login(client, "s3")
    for duty, username in ((Duty.COS, "ang"), (Duty.CDOS, "quek")):
        resp = client.post("/duty/roster/assign", data={
            "month": MONTH, "date": FRI.isoformat(), "duty": duty.value,
            "person_id": str(_pid(app, username)),
        }, follow_redirects=True)
        assert "Assigned." in resp.get_data(as_text=True)
    page = client.get(f"/duty/roster?month={MONTH}").get_data(as_text=True)
    fingerprint = re.search(r'name="fingerprint" value="([0-9a-f]{64})"', page).group(1)
    resp = client.post("/duty/roster/confirm",
                       data={"month": MONTH, "fingerprint": fingerprint},
                       follow_redirects=True)
    assert "Month confirmed" in resp.get_data(as_text=True)

    # --- S3 keys the standing content -----------------------------------------
    for section in RoSection:
        content = BOILERPLATE[section]
        if content:
            resp = client.post("/ro/boilerplate",
                               data={"section": section.value, "content": content},
                               follow_redirects=True)
            assert resp.status_code == 200
    for time_, text, recurrence, position in (
        ("06:00", "Roll call & Breakfast", "DAILY", "10"),
        ("", "SBA", "LAST_WORKING_DAY", "10"),
        ("", "LP", "DAILY", "20"),
    ):
        client.post("/ro/standing", data={
            "time": time_, "text": text, "recurrence": recurrence,
            "position": position,
        }, follow_redirects=True)
    mon, tue, wed, thu, fri = KEY_EVENTS
    client.post("/ro/key-events", data={
        "week": FRI.isoformat(), "mon": mon, "tue": tue, "wed": wed,
        "thu": thu, "fri": fri,
    }, follow_redirects=True)

    # --- The CDO/CDS of the date keys the daily slice --------------------------
    _switch(client, "quek")
    client.post("/ro/messages", data={"date": FRI.isoformat(), "messages": MESSAGES},
                follow_redirects=True)
    for time_, text in (
        ("06:20", "IPPT Stores Prep (Stores Party)"),
        ("06:45", "Registration of IPPT Participants at 10 C4I Bn Parade Square"),
        ("10:00", "FP"),
        ("11:00", "Ranging Ops Order Brief"),
        ("18:00", "Report to site"),
    ):
        client.post("/ro/extra/add",
                    data={"date": FRI.isoformat(), "time": time_, "text": text},
                    follow_redirects=True)

    # --- Any viewer's page renders EXACTLY the golden --------------------------
    _switch(client, "ang")
    page = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert _pre_text(page) == GOLDEN
    assert "No confirmed duty" not in page

    # --- A TP conduct starting that day auto-inserts; ARCTIC never does --------
    with app.app_context():
        db.session.add(Event(
            calendar=Calendar.TP, title="Site Testing",
            start_dt=datetime(2026, 6, 19, 9, 0), end_dt=datetime(2026, 6, 19, 17, 0),
            created_by_id=_pid(app, "s3"),
        ))
        db.session.add(Event(
            calendar=Calendar.ARCTIC, title="Contingency X",
            start_dt=datetime(2026, 6, 19, 9, 30), end_dt=datetime(2026, 6, 19, 11, 0),
            created_by_id=_pid(app, "s3"),
        ))
        db.session.commit()
    text = _pre_text(client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True))
    assert "0900H\n- Site Testing" in text
    assert "Contingency X" not in text

    # --- The CDO/CDS removes an item: derived document, zero stored text -------
    _switch(client, "quek")
    with app.app_context():
        from app.models import RoExtraItem
        item_id = db.session.query(RoExtraItem.id).filter_by(text="FP").scalar()
    resp = client.post("/ro/extra/remove",
                       data={"date": FRI.isoformat(), "item_id": str(item_id)},
                       follow_redirects=True)
    assert "removed" in resp.get_data(as_text=True)
    text = _pre_text(client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True))
    assert "1000H\n- FP" not in text
