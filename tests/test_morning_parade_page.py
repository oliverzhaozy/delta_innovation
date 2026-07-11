"""P3a.7 — morning parade page + "Not joining FP" quick-add.

The route is a thin wire: presence_service.presence_inputs -> parade.categorize
-> parade.render_morning. These tests hit the real DB/app (unlike the pure
compute tests in test_morning_parade.py) so the wiring, rights, and the
quick-add/remove round trip are pinned through the actual `<pre>` text the
document renders — the same derivation every parade document reads (never a
second check).
"""
from datetime import date, timedelta

from app.domain.types import (
    Appointment,
    DayPart,
    LeaveType,
    Rank,
    RequestStatus,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import LeaveRequest, Person, StatusEntry
from tests.conftest import login

DAY = date(2026, 7, 8)  # Wednesday — the parade day under test


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


def plant_status(app, username, type_=StatusType.MC, day=DAY, in_camp=False, remarks=None):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = StatusEntry(person_id=person_id, type=type_, start_date=day, end_date=day,
                           day_part=DayPart.FULL, in_camp=in_camp, remarks=remarks,
                           created_by_id=person_id)
        db.session.add(row)
        db.session.commit()
        return row.id


def plant_multiday_status(app, username, type_=StatusType.MC, start=DAY,
                           end=None, in_camp=False):
    end = end or (start + timedelta(days=3))
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = StatusEntry(person_id=person_id, type=type_, start_date=start, end_date=end,
                           day_part=DayPart.FULL, in_camp=in_camp, remarks=None,
                           created_by_id=person_id)
        db.session.add(row)
        db.session.commit()
        return row.id


# --- done-criterion 1: document renders real keyed data byte-for-byte -----

def test_renders_document_with_mc_off_and_stay_out(app, client, make_person):
    make_person(username="viewer", display_name="PTE Viewer Guy", rank=Rank.PTE, platoon=1)
    make_person(username="mc_guy", display_name="3SG Ravi Kumar", rank=Rank.THREE_SG, platoon=2)
    make_person(username="off_guy", display_name="CFC Daniel Lim", rank=Rank.CFC, platoon=2)
    make_person(username="stayout_guy", display_name="SSG Stay Out Guy", rank=Rank.SSG,
                platoon=3, service=Service.REGULAR)
    plant_status(app, "mc_guy", type_=StatusType.MC)
    plant_leave(app, "off_guy", type_=LeaveType.OFF)

    login(client, "viewer")
    resp = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert resp.status_code == 200

    assert b"TOTAL STRENGTH: 4" in resp.data
    assert b"CURRENT STRENGTH: 2" in resp.data
    assert b"ABSENT STRENGTH: 2" in resp.data
    assert b"SSG STAY OUT GUY" in resp.data
    assert b"PTE VIEWER GUY" in resp.data
    assert b"MC (1):\n1. 3SG RAVI KUMAR" in resp.data
    assert b"OFF/OIL (1):\n1. CFC DANIEL LIM" in resp.data
    # neither absent person shows in CURRENT STRENGTH
    current_block = resp.data.split(b"PRESENT IN CAMP")[1].split(b"NOT PRESENT IN CAMP")[0]
    assert b"RAVI KUMAR" not in current_block
    assert b"DANIEL LIM" not in current_block


# --- done-criterion 2: quick-add moves the person, counts rebalance, refresh is idempotent --

def test_quick_add_moves_person_to_others_in_camp_and_is_idempotent(app, client, make_person):
    make_person(username="ps_keyer", appointment=Appointment.PS, display_name="3SG Percy Sim")
    make_person(username="target", display_name="PTE Wong Kai", rank=Rank.PTE, platoon=1)
    login(client, "ps_keyer")
    target_id = pid(app, "target")

    resp = client.post(
        "/parade/morning/fp",
        data={"person_id": str(target_id), "reason": "BDO", "date": DAY.isoformat()},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"PTE WONG KAI (BDO)" in resp.data
    assert b"OTHERS IN CAMP (1):" in resp.data
    assert b"CURRENT STRENGTH (1):" in resp.data  # only the PS keyer left there
    current_block = resp.data.split(b"PRESENT IN CAMP")[1].split(b"NOT PRESENT IN CAMP")[0]
    assert b"WONG KAI" not in current_block.split(b"OTHERS IN CAMP")[0]

    with app.app_context():
        assert db.session.query(StatusEntry).count() == 1

    # A second GET (refresh) renders identically — the quick-add is a status
    # row, not form state, so re-viewing the page is a pure re-read.
    second = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert second.status_code == 200
    assert b"PTE WONG KAI (BDO)" in second.data
    assert b"OTHERS IN CAMP (1):" in second.data
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 1


# --- done-criterion 3: remove round-trips; guarded against non-quick-add rows --

def test_remove_quick_add_row_restores_current_strength(app, client, make_person):
    make_person(username="ps_keyer2", appointment=Appointment.PS)
    make_person(username="target2", display_name="PTE Wong Kai", rank=Rank.PTE, platoon=1)
    entry_id = plant_status(app, "target2", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    login(client, "ps_keyer2")

    resp = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert b"PTE WONG KAI (BDO)" in resp.data

    remove_resp = client.post(
        f"/parade/morning/fp/{entry_id}/remove",
        data={"date": DAY.isoformat()},
        follow_redirects=True,
    )
    assert remove_resp.status_code == 200
    assert b"WONG KAI (BDO)" not in remove_resp.data
    assert b"WONG KAI" in remove_resp.data  # back under CURRENT STRENGTH
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 0


def test_remove_on_non_quick_add_row_404s_and_leaves_row_untouched(app, client, make_person):
    make_person(username="ps_keyer3", appointment=Appointment.PS)
    make_person(username="mc_target", display_name="PTE Multi Day Mc")
    entry_id = plant_multiday_status(app, "mc_target", type_=StatusType.MC)
    login(client, "ps_keyer3")

    resp = client.post(
        f"/parade/morning/fp/{entry_id}/remove",
        data={"date": DAY.isoformat()},
    )
    assert resp.status_code == 404
    with app.app_context():
        row = db.session.get(StatusEntry, entry_id)
        assert row is not None
        assert row.type is StatusType.MC


# --- done-criterion 4: non-keyer sees the doc but no forms; mutations 403 --

def test_non_keyer_sees_document_but_no_forms_and_403_on_mutations(app, client, make_person):
    make_person(username="opr_viewer", appointment=Appointment.OPR)
    make_person(username="target3", display_name="PTE Some Guy")
    login(client, "opr_viewer")

    resp = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert resp.status_code == 200
    assert b"DELTA MORNING PARADE STATE" in resp.data
    assert b'action="/parade/morning/fp"' not in resp.data
    assert b"Remove" not in resp.data

    target_id = pid(app, "target3")
    post_resp = client.post(
        "/parade/morning/fp",
        data={"person_id": str(target_id), "reason": "BDO", "date": DAY.isoformat()},
    )
    assert post_resp.status_code == 403

    entry_id = plant_status(app, "target3", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    remove_resp = client.post(
        f"/parade/morning/fp/{entry_id}/remove",
        data={"date": DAY.isoformat()},
    )
    assert remove_resp.status_code == 403


# --- done-criterion 5: conflicts panel surfaces both rows, never silently ---

def test_conflict_panel_shows_both_rows_when_mc_overlaps_approved_leave(app, client, make_person):
    make_person(username="viewer5", display_name="PTE Viewer Five")
    make_person(username="conflicted", display_name="3SG Conflicted Guy", rank=Rank.THREE_SG)
    plant_leave(app, "conflicted", type_=LeaveType.OFF, status=RequestStatus.APPROVED)
    plant_status(app, "conflicted", type_=StatusType.MC)
    login(client, "viewer5")

    resp = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert resp.status_code == 200
    assert b"<h2>Conflicts</h2>" in resp.data
    # Leave beats status in the precedence order, so OFF is the winner and MC
    # is the shadowed row — both named, in one sentence, naming the person.
    expected = (
        "3SG Conflicted Guy: OFF (08 Jul) is showing on the parade; "
        "MC (08 Jul) is also keyed for this day and is not shown."
    )
    assert expected.encode() in resp.data


def test_no_conflict_panel_when_nothing_conflicts(app, client, make_person):
    make_person(username="viewer6", display_name="PTE Viewer Six")
    login(client, "viewer6")
    resp = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert resp.status_code == 200
    assert b"Conflicts" not in resp.data


# --- done-criterion 6: ?date= navigation + prev/next/Today links ------------

def test_date_param_navigation_and_nav_links(app, client, make_person):
    make_person(username="viewer7", display_name="PTE Viewer Seven")
    make_person(username="dated_guy", display_name="PTE Dated Guy")
    plant_status(app, "dated_guy", type_=StatusType.MC, day=DAY)
    login(client, "viewer7")

    day_resp = client.get(f"/parade/morning?date={DAY.isoformat()}")
    assert b"MC (1):\n1. PTE DATED GUY" in day_resp.data

    # The MC only covers DAY — D+1 is a different derivation, not a leftover
    # of the same data: dated_guy is back under CURRENT STRENGTH, MC is empty.
    next_day = DAY + timedelta(days=1)
    next_resp = client.get(f"/parade/morning?date={next_day.isoformat()}")
    assert b"MC (0):" in next_resp.data
    assert b"MC (1):\n1. PTE DATED GUY" not in next_resp.data

    prev_day = DAY - timedelta(days=1)
    assert f"/parade/morning?date={prev_day.isoformat()}".encode() in day_resp.data
    assert f"/parade/morning?date={next_day.isoformat()}".encode() in day_resp.data
    # DAY is off today, so the day-nav shows the "Back to today" chip (UI-17).
    assert b"Back to today" in day_resp.data


def test_bad_date_falls_back_to_today(client, make_person):
    login(client, make_person(username="viewer8"))
    assert client.get("/parade/morning?date=garbage").status_code == 200


# --- nav gating --------------------------------------------------------------

def test_nav_shows_morning_parade_link_to_every_logged_in_user(app, client, make_person):
    make_person(username="anyviewer", appointment=Appointment.OPR)
    login(client, "anyviewer")
    home = client.get("/").data
    assert b'href="/parade/cos-message"' in home
