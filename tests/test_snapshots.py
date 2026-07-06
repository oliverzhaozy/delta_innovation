"""P3a.8 — parade snapshots: append-only finalize.

Freezes the exact document text at copy time (TECH_PLAN "Retroactive drift":
a live-recomputed document changes when history changes; the snapshot must
not). The finalize route recomputes server-side through the same
presence_service.presence_inputs -> parade_domain.categorize -> render_morning
pipeline the GET /parade/morning page uses (see test_morning_parade_page.py)
— never the posted body — so a tampered hidden field can't falsify the
archival record. No update/delete route exists anywhere for a snapshot.
"""
from datetime import date

from app.domain import parade as parade_domain
from app.domain.types import Appointment, ParadeVariant, StatusType
from app.extensions import db
from app.models import ParadeSnapshot, Person, StatusEntry
from app.services import parade_service, presence_service
from tests.conftest import login

DAY = date(2026, 7, 8)  # Wednesday, matches test_morning_parade_page's convention


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def plant_status(app, username, type_=StatusType.MC, day=DAY, in_camp=False, remarks=None):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = StatusEntry(
            person_id=person_id, type=type_, start_date=day, end_date=day,
            in_camp=in_camp, remarks=remarks, created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _live_text(app, day):
    # Independent recompute through the exact same pipeline the app itself
    # uses, so "byte-identical" is checked against a second derivation, not a
    # copy of the stored value.
    with app.app_context():
        pairs = presence_service.presence_inputs(day)
        doc = parade_domain.categorize(day, pairs, "morning")
        return parade_domain.render_morning(doc)


# --- done-criterion 1: stored text byte-identical to the live compute ------

def test_finalize_stores_text_byte_identical_to_live_compute(app, client, make_person):
    make_person(username="ps_keyer", appointment=Appointment.PS, display_name="3SG Percy Sim")
    make_person(username="off_guy", display_name="CFC Daniel Lim")
    login(client, "ps_keyer")

    # Decision: the morning page gains a keyer-only "Finalize & copy" button.
    morning_page = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert b'action="/parade/morning/finalize"' in morning_page.data

    expected = _live_text(app, DAY)

    resp = client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})
    assert resp.status_code == 302

    with app.app_context():
        snap = db.session.query(ParadeSnapshot).one()
        assert snap.rendered_text == expected
        assert snap.variant is ParadeVariant.MORNING
        assert snap.date == DAY
        assert snap.finalized_by.username == "ps_keyer"
        snap_id = snap.id

    # Redirect goes to the new snapshot's own view page.
    assert resp.headers["Location"].endswith(f"/parade/snapshots/{snap_id}")
    detail = client.get(f"/parade/snapshots/{snap_id}")
    assert detail.status_code == 200
    assert expected.encode() in detail.data
    assert b"Finalized by 3SG Percy Sim" in detail.data


# --- done-criterion 2: keying after finalize changes the live page but not the snapshot --

def test_keying_after_finalize_changes_live_page_but_snapshot_is_byte_unchanged(app, client, make_person):
    make_person(username="ps_keyer2", appointment=Appointment.PS)
    make_person(username="target2", display_name="PTE Wong Kai")
    login(client, "ps_keyer2")

    client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})
    with app.app_context():
        snap = db.session.query(ParadeSnapshot).one()
        snap_id = snap.id
        frozen_text = snap.rendered_text

    # Key a new MC for the same date after the finalize.
    plant_status(app, "target2", type_=StatusType.MC, day=DAY)

    live = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert b"MC (1)" in live.data  # live recompute picked up the new keying

    with app.app_context():
        snap_after = db.session.get(ParadeSnapshot, snap_id)
        assert snap_after.rendered_text == frozen_text  # byte-unchanged
    assert frozen_text != _live_text(app, DAY)  # the two have now actually diverged


# --- done-criterion 3: second finalize appends, nothing overwritten --------

def test_second_finalize_appends_second_row_newest_first_nothing_overwritten(app, client, make_person):
    make_person(username="ps_keyer3", appointment=Appointment.PS)
    login(client, "ps_keyer3")

    client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})
    # Change headcount so the two finalized texts are provably distinct.
    make_person(username="new_guy", display_name="PTE New Guy")
    client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})

    with app.app_context():
        rows = parade_service.snapshots()
        assert len(rows) == 2
        newest, oldest = rows[0], rows[1]
        assert newest.id != oldest.id
        assert newest.rendered_text != oldest.rendered_text
        newest_id, oldest_id = newest.id, oldest.id

    listing = client.get("/parade/snapshots")
    assert listing.status_code == 200
    assert listing.data.count(b"Morning parade state") == 2
    newest_pos = listing.data.find(f"/parade/snapshots/{newest_id}".encode())
    oldest_pos = listing.data.find(f"/parade/snapshots/{oldest_id}".encode())
    assert newest_pos != -1 and oldest_pos != -1
    assert newest_pos < oldest_pos  # newest first


# --- done-criterion 4: RBAC — Opr views, 403 on finalize; PS finalizes ok ---

def test_opr_can_view_snapshots_but_gets_403_on_finalize_ps_finalizes_ok(app, make_person):
    make_person(username="opr_viewer", appointment=Appointment.OPR)
    make_person(username="ps_keyer4", appointment=Appointment.PS)

    ps_client = app.test_client()
    login(ps_client, "ps_keyer4")
    resp = ps_client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})
    assert resp.status_code == 302
    with app.app_context():
        snap_id = db.session.query(ParadeSnapshot).one().id

    opr_client = app.test_client()
    login(opr_client, "opr_viewer")

    home = opr_client.get("/")
    assert b'href="/parade/snapshots"' in home.data  # nav link for every logged-in user

    assert opr_client.get("/parade/snapshots").status_code == 200
    detail = opr_client.get(f"/parade/snapshots/{snap_id}")
    assert detail.status_code == 200

    morning_page = opr_client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert b'action="/parade/morning/finalize"' not in morning_page.data  # keyer-only button

    forbidden = opr_client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})
    assert forbidden.status_code == 403
    with app.app_context():
        assert db.session.query(ParadeSnapshot).count() == 1  # the 403 appended nothing


# --- done-criterion 5: tampered POST fields are ignored; server recomputes --

def test_tampered_post_fields_are_ignored_server_computed_text_stored(app, client, make_person):
    make_person(username="ps_keyer5", appointment=Appointment.PS)
    login(client, "ps_keyer5")

    expected = _live_text(app, DAY)
    resp = client.post(
        "/parade/morning/finalize",
        data={
            "date": DAY.isoformat(),
            "rendered_text": "HACKED\nTOTAL STRENGTH: 999",
            "text": "HACKED",
            "variant": "COS_MESSAGE",
        },
    )
    assert resp.status_code == 302

    with app.app_context():
        snap = db.session.query(ParadeSnapshot).one()
        assert snap.rendered_text == expected
        assert "HACKED" not in snap.rendered_text
        assert snap.variant is ParadeVariant.MORNING


# --- done-criterion 6: no update/delete route on snapshot URLs -------------

def test_no_mutation_routes_exist_on_snapshot_urls(app, client, make_person):
    make_person(username="ps_keyer6", appointment=Appointment.PS)
    login(client, "ps_keyer6")
    client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})
    with app.app_context():
        snap_id = db.session.query(ParadeSnapshot).one().id

    assert client.put(f"/parade/snapshots/{snap_id}").status_code in (404, 405)
    assert client.delete(f"/parade/snapshots/{snap_id}").status_code in (404, 405)
    assert client.post(f"/parade/snapshots/{snap_id}").status_code in (404, 405)
    assert client.post("/parade/snapshots").status_code in (404, 405)
    assert client.delete("/parade/snapshots").status_code in (404, 405)
    assert client.put("/parade/snapshots").status_code in (404, 405)

    with app.app_context():
        row = db.session.get(ParadeSnapshot, snap_id)
        assert row is not None  # still there, untouched
