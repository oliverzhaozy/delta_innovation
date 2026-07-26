"""P3a.7 — morning parade page + "Not joining FP" quick-add.

The route is a thin wire: presence_service.presence_inputs -> parade.categorize
-> parade.render_morning. These tests hit the real DB/app (unlike the pure
compute tests in test_morning_parade.py) so the wiring, rights, and the
quick-add/remove round trip are pinned through the actual `<pre>` text the
document renders — the same derivation every parade document reads (never a
second check).
"""
from datetime import timedelta

from app.domain.dates import today_sgt
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

DAY = today_sgt()  # the morning page is fixed to today; planted data lands here


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
    make_person(username="viewer", display_name="Viewer Guy", rank=Rank.PTE, platoon=1)
    make_person(username="mc_guy", display_name="Ravi Kumar", rank=Rank.THREE_SG, platoon=2)
    make_person(username="off_guy", display_name="Daniel Lim", rank=Rank.CFC, platoon=2)
    make_person(username="stayout_guy", display_name="Stay Out Guy", rank=Rank.SSG,
                platoon=3, service=Service.REGULAR)
    plant_status(app, "mc_guy", type_=StatusType.MC)
    plant_leave(app, "off_guy", type_=LeaveType.OFF)

    login(client, "viewer")
    resp = client.get("/parade/morning")
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
    make_person(username="ps_keyer", appointment=Appointment.PS, display_name="Percy Sim",
                rank=Rank.THREE_SG)
    make_person(username="target", display_name="Wong Kai", rank=Rank.PTE, platoon=1)
    login(client, "ps_keyer")
    target_id = pid(app, "target")

    resp = client.post(
        "/parade/morning/fp",
        data={"people": [str(target_id)], "reason": "BDO"},
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
    second = client.get("/parade/morning")
    assert second.status_code == 200
    assert b"PTE WONG KAI (BDO)" in second.data
    assert b"OTHERS IN CAMP (1):" in second.data
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 1


def test_fp_rows_list_is_parade_ordered_not_platoon_or_alphabetical(app, client, make_person):
    # UI-22: the remove list reads the same parade order the document above it
    # prints. The Opr is platoon 1 AND alphabetizes first — the old
    # platoon → name order led with her; on parade the Det Comd leads.
    make_person(username="fp_ps2", appointment=Appointment.PS, display_name="Keyer Guy",
                rank=Rank.TWO_SG, platoon=3)
    make_person(username="fp_aopr", display_name="Ann Opr", rank=Rank.PTE, platoon=1)
    make_person(username="fp_zdet", display_name="Zed Det", rank=Rank.THREE_SG,
                appointment=Appointment.DET_COMD, platoon=2)
    plant_status(app, "fp_aopr", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    plant_status(app, "fp_zdet", type_=StatusType.OTHER, in_camp=True, remarks="RP")
    login(client, "fp_ps2")

    body = client.get("/parade/morning").get_data(as_text=True)
    fp_list = body.split("Not joining FP")[1]
    assert fp_list.index("3SG Zed Det") < fp_list.index("PTE Ann Opr")


def test_bulk_add_expands_category_dedupes_and_skips_tagged(app, client, make_person):
    # UI-19: a category + an overlapping individual tick lands ONE row per
    # person; a re-post with a new reason skips everyone already tagged.
    make_person(username="ps_keyer_bulk", appointment=Appointment.PS,
                display_name="Percy Sim", rank=Rank.THREE_SG, platoon=2)
    make_person(username="p1_a", display_name="Alpha Guy", platoon=1)
    make_person(username="p1_b", display_name="Bravo Guy", platoon=1)
    make_person(username="p2_c", display_name="Charlie Guy", platoon=2)
    login(client, "ps_keyer_bulk")

    resp = client.post(
        "/parade/morning/fp",
        data={
            "categories": ["PLATOON_1"],
            "people": [str(pid(app, "p1_a")), str(pid(app, "p2_c"))],
            "reason": "BDO",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Added 3." in resp.data
    assert b"OTHERS IN CAMP (3):" in resp.data
    with app.app_context():
        rows = db.session.query(StatusEntry).all()
        assert len(rows) == 3
        assert all(row.remarks == "BDO" for row in rows)

    # Skip, never overwrite (owner decision 2026-07-11): the original reason
    # survives a re-post and the flash names the skip count.
    resp = client.post(
        "/parade/morning/fp",
        data={
            "categories": ["PLATOON_1"],
            "people": [str(pid(app, "p1_a")), str(pid(app, "p2_c"))],
            "reason": "NEW REASON",
        },
        follow_redirects=True,
    )
    assert b"Added 0. Skipped 3 already tagged." in resp.data
    with app.app_context():
        rows = db.session.query(StatusEntry).all()
        assert len(rows) == 3
        assert all(row.remarks == "BDO" for row in rows)


def test_bulk_add_empty_selection_creates_nothing(app, client, make_person):
    make_person(username="ps_keyer_none", appointment=Appointment.PS)
    login(client, "ps_keyer_none")

    resp = client.post(
        "/parade/morning/fp",
        data={"reason": "BDO"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Select at least one person or group." in resp.data
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 0


# --- done-criterion 3: bulk remove round-trips; non-quick-add rows survive ----

def test_remove_selected_rows_restores_current_strength(app, client, make_person):
    make_person(username="ps_keyer2", appointment=Appointment.PS)
    make_person(username="target2", display_name="Wong Kai", rank=Rank.PTE, platoon=1)
    make_person(username="target2b", display_name="Lim Boon", rank=Rank.PTE, platoon=1)
    first = plant_status(app, "target2", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    second = plant_status(app, "target2b", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    login(client, "ps_keyer2")

    resp = client.get("/parade/morning")
    assert b"PTE WONG KAI (BDO)" in resp.data
    assert b"PTE LIM BOON (BDO)" in resp.data
    # The remove form is a SIBLING of the add form, never nested inside it —
    # nesting would break the picker script's one-form hook.
    assert resp.data.count(b"data-people-picker") == 1
    assert resp.data.count(b'action="/parade/morning/fp/remove"') == 1

    remove_resp = client.post(
        "/parade/morning/fp/remove",
        data={"entry_ids": [str(first), str(second)]},
        follow_redirects=True,
    )
    assert remove_resp.status_code == 200
    assert b"Removed 2." in remove_resp.data
    assert b"WONG KAI (BDO)" not in remove_resp.data
    assert b"LIM BOON (BDO)" not in remove_resp.data
    # Both are back under CURRENT STRENGTH.
    assert b"WONG KAI" in remove_resp.data
    assert b"LIM BOON" in remove_resp.data
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 0


def test_mixed_batch_skips_non_quick_add_rows_and_reports_the_count(app, client, make_person):
    # The shape guard survives the move to bulk: a multiday MC id smuggled into
    # the batch is skipped and counted, while the real quick-add still goes.
    make_person(username="ps_keyer3", appointment=Appointment.PS)
    make_person(username="mc_target", display_name="Multi Day Mc")
    make_person(username="fp_target", display_name="Quick Add", rank=Rank.PTE, platoon=1)
    mc_id = plant_multiday_status(app, "mc_target", type_=StatusType.MC)
    fp_id = plant_status(app, "fp_target", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    login(client, "ps_keyer3")

    resp = client.post(
        "/parade/morning/fp/remove",
        data={"entry_ids": [str(fp_id), str(mc_id)]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Removed 1. Skipped 1." in resp.data
    with app.app_context():
        row = db.session.get(StatusEntry, mc_id)
        assert row is not None
        assert row.type is StatusType.MC
        assert db.session.get(StatusEntry, fp_id) is None


def test_remove_with_nothing_selected_is_an_error_and_writes_nothing(app, client, make_person):
    make_person(username="ps_keyer3b", appointment=Appointment.PS)
    make_person(username="target3b", display_name="Stays Put", rank=Rank.PTE, platoon=1)
    entry_id = plant_status(app, "target3b", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    login(client, "ps_keyer3b")

    resp = client.post("/parade/morning/fp/remove", data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Select at least one entry." in resp.data
    with app.app_context():
        assert db.session.get(StatusEntry, entry_id) is not None


# --- done-criterion 4: non-keyer sees the doc but no forms; mutations 403 --

def test_non_keyer_sees_document_but_no_forms_and_403_on_mutations(app, client, make_person):
    make_person(username="opr_viewer", appointment=Appointment.OPR)
    make_person(username="target3", display_name="Some Guy")
    login(client, "opr_viewer")

    resp = client.get("/parade/morning")
    assert resp.status_code == 200
    assert b"DELTA MORNING PARADE STATE" in resp.data
    assert b'action="/parade/morning/fp"' not in resp.data
    assert b"Remove" not in resp.data

    target_id = pid(app, "target3")
    post_resp = client.post(
        "/parade/morning/fp",
        data={"people": [str(target_id)], "reason": "BDO"},
    )
    assert post_resp.status_code == 403

    entry_id = plant_status(app, "target3", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    remove_resp = client.post(
        "/parade/morning/fp/remove",
        data={"entry_ids": [str(entry_id)]},
    )
    assert remove_resp.status_code == 403


# --- done-criterion 5: conflicts panel surfaces both rows, never silently ---

def test_conflict_panel_shows_both_rows_when_mc_overlaps_approved_leave(app, client, make_person):
    make_person(username="viewer5", display_name="Viewer Five")
    make_person(username="conflicted", display_name="Conflicted Guy", rank=Rank.THREE_SG)
    plant_leave(app, "conflicted", type_=LeaveType.OFF, status=RequestStatus.APPROVED)
    plant_status(app, "conflicted", type_=StatusType.MC)
    login(client, "viewer5")

    resp = client.get("/parade/morning")
    assert resp.status_code == 200
    assert b"<h2>Conflicts</h2>" in resp.data
    # Leave beats status in the precedence order, so OFF is the winner and MC
    # is the shadowed row — both named, in one sentence, naming the person.
    stamp = DAY.strftime("%d %b")
    expected = (
        f"3SG Conflicted Guy: OFF ({stamp}) is showing on the parade; "
        f"MC ({stamp}) is also keyed for this day and is not shown."
    )
    assert expected.encode() in resp.data


def test_no_conflict_panel_when_nothing_conflicts(app, client, make_person):
    make_person(username="viewer6", display_name="Viewer Six")
    login(client, "viewer6")
    resp = client.get("/parade/morning")
    assert resp.status_code == 200
    assert b"Conflicts" not in resp.data


# --- done-criterion 6: the page is today-only, with no day navigation -------

def test_page_always_shows_today_and_has_no_day_nav(app, client, make_person):
    # The morning page is fixed to today: today's MC lands in the MC block,
    # tomorrow's is a different derivation (that person is present today), and
    # there is no ?date= walk or "Back to today" chip to leave the day.
    make_person(username="viewer7", display_name="Viewer Seven")
    make_person(username="today_mc", display_name="Today Mc", rank=Rank.THREE_SG)
    make_person(username="tomorrow_mc", display_name="Tomorrow Mc", rank=Rank.THREE_SG)
    plant_status(app, "today_mc", type_=StatusType.MC, day=DAY)
    plant_status(app, "tomorrow_mc", type_=StatusType.MC, day=DAY + timedelta(days=1))
    login(client, "viewer7")

    resp = client.get("/parade/morning")
    assert resp.status_code == 200
    assert b"MC (1):\n1. 3SG TODAY MC" in resp.data
    # Tomorrow's MC does not bleed into today — the count stays at one.
    assert b"MC (2):" not in resp.data
    # No day navigation survives: no ?date= links, no "Back to today" chip.
    assert b"?date=" not in resp.data
    assert b"Back to today" not in resp.data


# --- nav gating --------------------------------------------------------------

def test_nav_shows_morning_parade_link_to_every_logged_in_user(app, client, make_person):
    make_person(username="anyviewer", appointment=Appointment.OPR)
    login(client, "anyviewer")
    home = client.get("/").data
    assert b'href="/parade/cos-message"' in home
