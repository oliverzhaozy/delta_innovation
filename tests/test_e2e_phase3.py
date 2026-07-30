"""P3b.7 — the Phase 3 end-to-end walk, via the test client only.

One S3 keys everything a real evening needs, then every Phase-3 surface is
checked against the SAME derivation: S3 keys an MC and a regular's out-of-camp
status -> COS message (compiled D-1) categorizes both -> roll call balances ->
FP quick-add moves a man to OTHERS IN CAMP -> morning parade shows both
absences -> the meal-indent count reads the same derivation (decisions j/cc) -> and
the ledger is untouched, because keying parade data never moves a balance.
"""
from datetime import timedelta

from app.domain.dates import today_sgt
from app.domain.types import Appointment, Rank, Service
from app.extensions import db
from app.models import LedgerEntry, Person
from app.services import meal_service
from tests.conftest import login

# The live pages are date-fixed now: morning/roll call = today (D), COS message
# = tomorrow (NEXT). D is today so the morning/roll-call/meals surfaces line up,
# and the pieces that must show on the COS page are keyed to cover NEXT too.
D = today_sgt()
NEXT = D + timedelta(days=1)


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def test_phase3_end_to_end(app, client, make_person):
    # Roster: the keying S3 (det comd, admin — mirrors the real seed), a
    # regular OC, a stay-in NSF, a stay-out NSF, and an NSF about to be MC.
    make_person(username="s3_keyer", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
                company_role="S3", is_admin=True, display_name="Dylan Chey")
    make_person(username="oc_boss", rank=Rank.CPT, appointment=Appointment.OC,
                service=Service.REGULAR, platoon=None, display_name="Marcus Leong")
    make_person(username="opr_in", rank=Rank.CFC, display_name="Ethan Siow")
    make_person(username="opr_out", rank=Rank.CPL, stay_out=True, display_name="Wayne Loo")
    make_person(username="opr_mc", display_name="Caleb Zhuo")
    login(client, "s3_keyer")

    # --- S3 keys an MC and the regular OC's out-of-camp status (both D..NEXT) --
    resp = client.post("/parade/statuses/new", data={
        "person_id": str(_pid(app, "opr_mc")), "type": "MC",
        "start_date": D.isoformat(), "end_date": NEXT.isoformat(),
        "day_part": "FULL", "in_camp": "DEFAULT", "remarks": "",
    })
    assert resp.status_code == 302
    # The COS page is compiled for tomorrow (NEXT), so the regular's status is
    # keyed to cover D..NEXT — it must show on both today's morning and
    # tomorrow's COS message. A regular has no in-app leave (P9.3, ARCTIC FOE
    # owns that), so an out-of-camp status is what takes one off the parade.
    resp = client.post("/parade/statuses/new", data={
        "person_id": str(_pid(app, "oc_boss")), "type": "OTHER",
        "start_date": D.isoformat(), "end_date": NEXT.isoformat(),
        "day_part": "FULL", "in_camp": "OUT", "remarks": "Overseas",
    })
    assert resp.status_code == 302

    # --- COS message (fixed to tomorrow, NEXT) -------------------------------
    page = client.get("/parade/cos-message")
    assert page.status_code == 200
    assert b"CALEB ZHUO" in page.data          # MC category (covers NEXT)
    assert b"MARCUS LEONG" in page.data        # regular's keyed status (covers NEXT)

    # --- Roll call (fixed to today, D) balances ------------------------------
    page = client.get("/parade/roll-call")
    assert b"CURRENT STRENGTH" in page.data
    assert b"out of balance" not in page.data

    # --- FP quick-add moves the stay-in man to OTHERS IN CAMP ----------------
    resp = client.post("/parade/morning/fp", data={
        "people": [str(_pid(app, "opr_in"))], "reason": "BDO",
    })
    assert resp.status_code == 302
    page = client.get("/parade/morning")
    assert b"ETHAN SIOW (BDO)" in page.data

    # --- The NSF count reads the SAME derivation (decisions j/cc) ------------
    # Hand-derived: s3, opr_in (in camp, just not at FP), opr_out (stay-out
    # dissolves by day) = 3 NSFs. Cross-checked against the service so the page
    # and the derivation can never be asserted apart.
    with app.app_context():
        expected, imbalance = meal_service.compute_for(D)
        assert imbalance is None
        assert expected == 3
    page = client.get(f"/meals/day?date={D.isoformat()}")
    assert b'id="meal-expected">3<' in page.data

    # --- Morning parade agrees ------------------------------------------------
    absent = client.get("/parade/morning").data.split(b"NOT PRESENT IN CAMP")[1]
    assert b"CALEB ZHUO" in absent    # MC
    assert b"MARCUS LEONG" in absent  # regular's keyed out-of-camp status

    # --- Keying parade data never touches a balance ---------------------------
    with app.app_context():
        assert db.session.query(LedgerEntry).count() == 0
