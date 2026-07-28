"""P6.7 — the Phase 6 end-to-end walk, via the test client only.

The S3 builds the owner's sample period through the real UI: create the
5–13 Jul period, fill all ten slots, and the builder's <pre> renders EXACTLY
the P6.5 golden (phones included). Then a det member declares overseas — the
flag appears on the builder AND his pick-list entry (the replacement list),
his leave request shows the manning panel to the OC, and retracting the
declaration clears the flag with zero writes to any flag.
"""
import html as html_lib
import re
from datetime import date

from app.domain.types import Appointment, Rank, Service
from app.extensions import db
from app.models import ManningPeriod, OverseasDeclaration, Person
from tests.conftest import login
from tests.test_manning_domain import GOLDEN

START, END = date(2026, 7, 5), date(2026, 7, 13)

CAST = [
    # (username, rank, appointment, display_name, phone)
    ("oc", Rank.CPT, Appointment.OC, "Wong Li Xuan", "9190 9702"),
    ("pc1", Rank.LTA, Appointment.PC, "Quek Jing Yu", "9736 3276"),
    ("p2ic3", Rank.THREE_WO, Appointment.P2IC, "Wong Jingheng", "9798 3466"),
    ("jeymus", Rank.TWO_SG, Appointment.DET_COMD, "Jeymus Tan", "8518 3687"),
    ("weixuan", Rank.THREE_SG, Appointment.OPR, "Wong Wei Xuan", "9683 9858"),
    ("ang", Rank.CPL, Appointment.OPR, "Ang Cheng Ze", "8435 8990"),
    ("raybriel", Rank.TWO_SG, Appointment.PS, "Raybriel Wong", "9382 3212"),
    ("loy", Rank.THREE_SG, Appointment.OPR, "Loy Qiyuan", "9673 7123"),
    ("xu", Rank.THREE_SG, Appointment.OPR, "Xu Xiangrui", "8218 8905"),
    ("samuel", Rank.LCP, Appointment.OPR, "Samuel Lim", "9838 7704"),
]

ASSIGNMENTS = [
    ("TU_COMD", "oc", ""),
    ("TU_PLANNER", "pc1", ""),
    ("TU_DET_COMD", "p2ic3", "1"),
    ("DET_PERSONNEL", "jeymus", "1"),
    ("DET_PERSONNEL", "weixuan", "1"),
    ("DET_PERSONNEL", "ang", "1"),
    ("TU_DET_COMD", "raybriel", "2"),
    ("DET_PERSONNEL", "loy", "2"),
    ("DET_PERSONNEL", "xu", "2"),
    ("DET_PERSONNEL", "samuel", "2"),
]


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def _switch(client, username):
    client.post("/logout")
    login(client, username)


def _pre_text(page_html):
    match = re.search(r'<pre id="manningtext"[^>]*>(.*?)</pre>', page_html, re.S)
    assert match, "the builder must render the document <pre>"
    return html_lib.unescape(match.group(1))


def test_phase6_end_to_end(app, client, make_person):
    # --- 1. Seed: the S3 + the sample's ten people (phones keyed) ------------
    make_person(username="s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
                company_role="S3", display_name="Dylan Chey")
    for username, rank, appt, name, _phone in CAST:
        make_person(
            username=username, rank=rank, appointment=appt, display_name=name,
            platoon=None if appt is Appointment.OC else 1,
            service=Service.REGULAR if appt is Appointment.OC else Service.NSF,
        )
    with app.app_context():
        for username, _rank, _appt, _name, phone in CAST:
            db.session.query(Person).filter_by(username=username).one().phone = phone
        db.session.commit()

    # --- 2. S3 creates the period and fills every slot through the UI --------
    login(client, "s3")
    client.post("/manning/new", data={
        "start_date": START.isoformat(), "end_date": END.isoformat(),
    }, follow_redirects=True)
    with app.app_context():
        period_id = db.session.query(ManningPeriod.id).scalar()
    for slot, username, det in ASSIGNMENTS:
        resp = client.post(f"/manning/{period_id}/assign", data={
            "slot": slot, "person_id": str(_pid(app, username)), "det_number": det,
        }, follow_redirects=True)
        assert "Assigned." in resp.get_data(as_text=True), (slot, username)

    # --- 3. The builder's document IS the golden, byte for byte --------------
    page = client.get(f"/manning/{period_id}").get_data(as_text=True)
    assert _pre_text(page) == GOLDEN
    assert "Unfilled" not in page

    # --- 4. A det member declares overseas: flags on builder + pick list -----
    _switch(client, "ang")
    # Deliberately NOT following the redirect: the period is the owner's
    # historical sample, so this declaration has already ended, and
    # /overseas/mine would purge it on sight (owner 2026-07-28). The manning
    # flag is what this walk is about, and it flags PENDING rows too.
    resp = client.post("/overseas/declare", data={
        "start_date": date(2026, 7, 10).isoformat(),
        "end_date": date(2026, 7, 12).isoformat(),
        "destination": "Japan",
    })
    assert resp.status_code == 302

    _switch(client, "s3")
    html = client.get(f"/manning/{period_id}").get_data(as_text=True)
    assert 'badge rejected">&#9888; Overseas (Japan) 10 Jul – 12 Jul' in html
    # The replacement list: unflagged Det Personnel candidates sort first,
    # the declared traveller carries his reason in the option text.
    select = re.search(r'data-slot="DET_PERSONNEL".*?</select>', html, re.S).group(0)
    assert "Overseas (Japan)" in select
    assert select.index("Wong Wei Xuan") < select.index("Ang Cheng Ze")

    # --- 5. His leave request shows the manning panel to the OC --------------
    _switch(client, "ang")
    client.post("/leave/new", data={
        "type": "OFF", "start_date": date(2026, 7, 6).isoformat(),
        "end_date": date(2026, 7, 6).isoformat(), "day_part": "FULL", "reason": "",
    }, follow_redirects=True)
    with app.app_context():
        from app.models import LeaveRequest
        req_id = db.session.query(LeaveRequest.id).filter_by(
            person_id=_pid(app, "ang")).scalar()
    _switch(client, "pc1")
    html = client.get(f"/leave/{req_id}").get_data(as_text=True)
    assert "Manning periods on these dates" in html
    assert "Det Personnel" in html

    # --- 6. Retracting the declaration clears the flag: derived, never stored -
    _switch(client, "ang")
    with app.app_context():
        decl_id = db.session.query(OverseasDeclaration.id).scalar()
    client.post(f"/overseas/{decl_id}/retract", follow_redirects=True)
    _switch(client, "s3")
    html = client.get(f"/manning/{period_id}").get_data(as_text=True)
    assert "Overseas (Japan)" not in html
