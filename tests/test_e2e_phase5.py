"""P5.6 — the Phase 5 end-to-end walk, via the test client only.

The whole stack reproduces the owner's normalized sample: S3 assigns the
duty roster for 19 Jun 2026, keys the boilerplate, and plots the week's TP
conducts (the key-events source since the 2026-07-24 revision); the CDO/CDS
of the date pastes the messages blob and keys the day's timeline items; any
viewer's /ro page then renders the P5.3 golden — byte-identical except the
Friday key line, which now derives from TP (the sample's hand-typed IPPT/
Ranging entries would double into the timeline if plotted as Fri conducts).
Then a TP conduct starting that day auto-inserts into timeline AND key
events, and a removed extra item disappears — derived, never stored.
"""
import html as html_lib
import re
from datetime import date, datetime

from app.domain.types import Appointment, Calendar, Duty, Rank, RoSection
from app.extensions import db
from app.models import Event, Person
from tests.conftest import login
from tests.test_ro_domain import BOILERPLATE, GOLDEN, MESSAGES

FRI = date(2026, 6, 19)
MONTH = "2026-06"

# The golden with its Friday key line as the TP calendar derives it: the
# Mon–Thu lines reproduce exactly from the plotted conducts; Friday's own
# conducts are keyed as timeline extras (per the sample), so the key line
# carries just the week-long backdrop.
EXPECTED = "\n".join(GOLDEN.splitlines()[:-1] + ["Fri - Site Testing"])


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

    # --- S3 assigns the date's duties through the roster UI -------------------
    # An assigned row is live immediately (owner 2026-07-27) — the RO reads it
    # with no confirm step in between.
    login(client, "s3")
    for duty, username in ((Duty.COS, "ang"), (Duty.CDOS, "quek")):
        resp = client.post("/duty/roster/assign", data={
            "month": MONTH, "date": FRI.isoformat(), "duty": duty.value,
            "person_id": str(_pid(app, username)),
        }, follow_redirects=True)
        assert "Assigned." in resp.get_data(as_text=True)

    # --- S3 keys the boilerplate and plots the week's TP conducts --------------
    for section in RoSection:
        content = BOILERPLATE[section]
        if content:
            resp = client.post("/ro/boilerplate",
                               data={"section": section.value, "content": content},
                               follow_redirects=True)
            assert resp.status_code == 200
    with app.app_context():
        s3_id = _pid(app, "s3")
        for title, start_dt, end_dt in (
            ("Wolf PT", datetime(2026, 6, 15, 8, 0), datetime(2026, 6, 15, 9, 0)),
            ("PMCS/EAS/MPT", datetime(2026, 6, 15, 10, 0), datetime(2026, 6, 15, 12, 0)),
            ("Site Testing", datetime(2026, 6, 15, 13, 0), datetime(2026, 6, 19, 17, 0)),
            ("Coy PT", datetime(2026, 6, 17, 8, 0), datetime(2026, 6, 17, 9, 0)),
            ("CS", datetime(2026, 6, 17, 10, 0), datetime(2026, 6, 17, 11, 0)),
        ):
            db.session.add(Event(
                calendar=Calendar.TP, title=title, start_dt=start_dt,
                end_dt=end_dt, created_by_id=s3_id,
            ))
        db.session.commit()

    # --- The CDO/CDS of the date keys the daily slice --------------------------
    _switch(client, "quek")
    client.post("/ro/messages", data={"date": FRI.isoformat(), "messages": MESSAGES},
                follow_redirects=True)
    for time_, text in (
        ("06:00", "Roll call & Breakfast"),
        ("06:20", "IPPT Stores Prep (Stores Party)"),
        ("06:45", "Registration of IPPT Participants at 10 C4I Bn Parade Square"),
        ("10:00", "FP"),
        ("11:00", "Ranging Ops Order Brief"),
        ("18:00", "Report to site"),
        ("", "SBA"),
        ("", "LP"),
    ):
        client.post("/ro/extra/add",
                    data={"date": FRI.isoformat(), "time": time_, "text": text},
                    follow_redirects=True)

    # --- Any viewer's page renders the golden (derived Friday key line) --------
    _switch(client, "ang")
    page = client.get(f"/ro?date={FRI.isoformat()}").get_data(as_text=True)
    assert _pre_text(page) == EXPECTED
    assert "No confirmed duty" not in page

    # --- A TP conduct starting that day auto-inserts into the timeline AND the
    # --- key-events line; ARCTIC never enters the RO ---------------------------
    with app.app_context():
        db.session.add(Event(
            calendar=Calendar.TP, title="IPPT",
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
    assert "0900H\n- IPPT" in text
    assert "Fri - IPPT, Site Testing" in text
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
