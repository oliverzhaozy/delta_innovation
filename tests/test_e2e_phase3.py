"""P3b.7 — the Phase 3 end-to-end walk, via the test client only.

One S3 keys everything a real evening needs, then every Phase-3 surface is
checked against the SAME derivation: S3 keys an MC and a regular's direct
absence -> COS message (compiled D-1) categorizes both -> roll call balances ->
FP quick-add moves a man to OTHERS IN CAMP -> morning parade shows both
absences -> the NSF meal counters read the same derivation (decision j) -> and
the ledger is untouched, because keying parade data never moves a balance.
"""
from datetime import date, timedelta

from app.domain.types import Appointment, Rank, Service
from app.extensions import db
from app.models import LedgerEntry, Person
from app.services import meal_service
from tests.conftest import login

D = date(2026, 7, 8)       # Wednesday — the parade day under test
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

    # --- S3 keys an MC (covers D..D+1) and the OC's direct absence (D only) --
    resp = client.post("/parade/statuses/new", data={
        "person_id": str(_pid(app, "opr_mc")), "type": "MC",
        "start_date": D.isoformat(), "end_date": NEXT.isoformat(),
        "day_part": "FULL", "in_camp": "DEFAULT", "remarks": "",
    })
    assert resp.status_code == 302
    resp = client.post("/parade/direct-absences/new", data={
        "person_id": str(_pid(app, "oc_boss")), "type": "LEAVE",
        "start_date": D.isoformat(), "end_date": D.isoformat(),
        "day_part": "FULL", "remarks": "Overseas leave",
    })
    assert resp.status_code == 302

    # --- COS message for D (compiled the evening of D-1) ---------------------
    page = client.get(f"/parade/cos-message?date={D.isoformat()}")
    assert page.status_code == 200
    assert b"CALEB ZHUO" in page.data          # MC category
    assert b"MARCUS LEONG" in page.data        # regular's keyed absence

    # --- Roll call for D balances --------------------------------------------
    page = client.get(f"/parade/roll-call?date={D.isoformat()}")
    assert b"CURRENT STRENGTH" in page.data
    assert b"out of balance" not in page.data

    # --- FP quick-add moves the stay-in man to OTHERS IN CAMP ----------------
    resp = client.post("/parade/morning/fp", data={
        "date": D.isoformat(), "people": [str(_pid(app, "opr_in"))], "reason": "BDO",
    })
    assert resp.status_code == 302
    page = client.get(f"/parade/morning?date={D.isoformat()}")
    assert b"ETHAN SIOW (BDO)" in page.data

    # --- NSF counters read the SAME derivation (decision j) ------------------
    # Hand-derived: day = s3, opr_in (in camp, just not at FP), opr_out
    # (dissolves by day) = 3 NSFs; overnight D->D+1 = s3, opr_in (quick-add was
    # single-day) = 2 NSFs. Cross-checked against the service so the page and
    # the derivation can never be asserted apart.
    with app.app_context():
        counts, imbalance = meal_service.compute_for(D)
        assert imbalance is None
        assert (counts.day_in_camp, counts.overnight) == (3, 2)
    page = client.get(f"/meals?date={D.isoformat()}")
    assert b'id="nsf-day">3<' in page.data
    assert b'id="nsf-overnight">2<' in page.data

    # --- Morning parade agrees ------------------------------------------------
    absent = client.get(
        f"/parade/morning?date={D.isoformat()}"
    ).data.split(b"NOT PRESENT IN CAMP")[1]
    assert b"CALEB ZHUO" in absent    # MC
    assert b"MARCUS LEONG" in absent  # regular's keyed direct absence

    # --- Keying parade data never touches a balance ---------------------------
    with app.app_context():
        assert db.session.query(LedgerEntry).count() == 0
