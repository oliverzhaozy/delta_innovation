"""P8.1/P8.2/P8.3 — parade snapshot archive.

The service tests pin append-only dedup behaviour directly; the route tests
pin that Copy archives the SERVER-rendered text (never client-sent), that the
history pages list/filter/detail, and the copy-button data seams that the
fire-and-forget JS reads (there is no JS runner in the repo, so attribute
presence/absence is the testable boundary).
"""
from datetime import date, timedelta

from app.domain.dates import today_sgt
from app.domain.types import ParadeVariant
from app.extensions import db
from app.models import ParadeSnapshot, Person
from app.services import parade_service
from tests.conftest import login

DAY = date(2026, 7, 20)
TODAY = today_sgt()
TOMORROW = TODAY + timedelta(days=1)


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


# --- T3: service (append-only, dedup-on-identical) --------------------------

def test_save_snapshot_stores_text_author_and_time(app, make_person):
    make_person(username="snap_author")
    pid = _pid(app, "snap_author")
    with app.app_context():
        snap = parade_service.save_snapshot(
            DAY, ParadeVariant.MORNING, "hello parade", created_by_id=pid
        )
        db.session.commit()
        assert snap is not None
        stored = db.session.get(ParadeSnapshot, snap.id)
        assert stored.rendered_text == "hello parade"
        assert stored.created_by_id == pid
        assert stored.date == DAY
        assert stored.variant is ParadeVariant.MORNING
        assert stored.created_at is not None


def test_identical_resave_is_skipped(app, make_person):
    make_person(username="snap_dedup")
    pid = _pid(app, "snap_dedup")
    with app.app_context():
        parade_service.save_snapshot(DAY, ParadeVariant.MORNING, "same", created_by_id=pid)
        db.session.commit()
        again = parade_service.save_snapshot(DAY, ParadeVariant.MORNING, "same", created_by_id=pid)
        db.session.commit()
        assert again is None
        count = (
            db.session.query(ParadeSnapshot)
            .filter_by(date=DAY, variant=ParadeVariant.MORNING)
            .count()
        )
        assert count == 1


def test_changed_text_appends(app, make_person):
    make_person(username="snap_change")
    pid = _pid(app, "snap_change")
    with app.app_context():
        parade_service.save_snapshot(DAY, ParadeVariant.MORNING, "first", created_by_id=pid)
        db.session.commit()
        second = parade_service.save_snapshot(
            DAY, ParadeVariant.MORNING, "second", created_by_id=pid
        )
        db.session.commit()
        assert second is not None
        count = (
            db.session.query(ParadeSnapshot)
            .filter_by(date=DAY, variant=ParadeVariant.MORNING)
            .count()
        )
        assert count == 2


def test_variants_are_independent(app, make_person):
    make_person(username="snap_variant")
    pid = _pid(app, "snap_variant")
    with app.app_context():
        # Identical date + text under a different variant is a distinct slot:
        # the dedup guard keys on (date, variant), so this must NOT be skipped.
        parade_service.save_snapshot(DAY, ParadeVariant.MORNING, "text", created_by_id=pid)
        other = parade_service.save_snapshot(
            DAY, ParadeVariant.ROLL_CALL, "text", created_by_id=pid
        )
        db.session.commit()
        assert other is not None
        assert db.session.query(ParadeSnapshot).filter_by(date=DAY).count() == 2


# --- T4: POST /parade/snapshot archives server-rendered text ----------------

def test_copy_post_archives_server_rendered_text(app, client, make_person):
    make_person(username="snap_poster", display_name="Snap Poster")
    login(client, "snap_poster")

    resp = client.post("/parade/snapshot", data={"variant": "morning"})
    assert resp.status_code == 204

    with app.app_context():
        expected = parade_service.build_doc(TODAY, ParadeVariant.MORNING).text
        rows = db.session.query(ParadeSnapshot).all()
        assert len(rows) == 1
        assert rows[0].date == TODAY
        assert rows[0].variant is ParadeVariant.MORNING
        assert rows[0].rendered_text == expected


def test_cos_snapshot_stores_tomorrow_and_respects_cos(app, client, make_person):
    make_person(username="snap_cos_viewer", display_name="Cos Viewer")
    make_person(username="snap_cos_person", display_name="Chosen Cos")
    login(client, "snap_cos_viewer")
    cos_pid = _pid(app, "snap_cos_person")

    resp = client.post("/parade/snapshot", data={"variant": "cos", "cos": str(cos_pid)})
    assert resp.status_code == 204

    with app.app_context():
        cos_person = db.session.get(Person, cos_pid)
        expected = parade_service.build_doc(
            TOMORROW, ParadeVariant.COS_MESSAGE, cos_person=cos_person
        ).text
        row = db.session.query(ParadeSnapshot).filter_by(variant=ParadeVariant.COS_MESSAGE).one()
        assert row.date == TOMORROW
        assert row.rendered_text == expected


def test_unknown_variant_is_400(app, client, make_person):
    make_person(username="snap_bad_variant")
    login(client, "snap_bad_variant")
    resp = client.post("/parade/snapshot", data={"variant": "garbage"})
    assert resp.status_code == 400
    with app.app_context():
        assert db.session.query(ParadeSnapshot).count() == 0


def test_anonymous_snapshot_post_is_redirected_and_writes_nothing(app, client, make_person):
    make_person(username="snap_ghost")  # exists, but we do NOT log in
    resp = client.post("/parade/snapshot", data={"variant": "morning"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with app.app_context():
        assert db.session.query(ParadeSnapshot).count() == 0


# --- T4: history list / filter / detail -------------------------------------

def test_history_lists_and_filters_by_date(app, client, make_person):
    make_person(username="hist_viewer", display_name="Hist Viewer")
    login(client, "hist_viewer")
    pid = _pid(app, "hist_viewer")
    with app.app_context():
        parade_service.save_snapshot(DAY, ParadeVariant.MORNING, "day20 text", created_by_id=pid)
        parade_service.save_snapshot(
            DAY + timedelta(days=1), ParadeVariant.ROLL_CALL, "day21 text", created_by_id=pid
        )
        db.session.commit()

    all_resp = client.get("/parade/history")
    assert all_resp.status_code == 200
    assert b"Morning parade state" in all_resp.data
    assert b"Roll call state" in all_resp.data
    assert b"Hist Viewer" in all_resp.data  # copier named

    filtered = client.get(f"/parade/history?date={DAY.isoformat()}")
    assert filtered.status_code == 200
    assert DAY.strftime("%d %b %Y").encode() in filtered.data
    # The other date's card is filtered out (its variant label absent).
    assert b"Roll call state" not in filtered.data


def test_history_empty_state(app, client, make_person):
    make_person(username="hist_empty_viewer")
    login(client, "hist_empty_viewer")
    resp = client.get("/parade/history")
    assert resp.status_code == 200
    assert b"No snapshots" in resp.data


def test_history_detail_shows_verbatim_text_and_no_snapshot_attr(app, client, make_person):
    make_person(username="hist_detail_viewer")
    login(client, "hist_detail_viewer")
    pid = _pid(app, "hist_detail_viewer")
    with app.app_context():
        snap = parade_service.save_snapshot(
            DAY, ParadeVariant.MORNING, "verbatim snapshot body", created_by_id=pid
        )
        db.session.commit()
        snap_id = snap.id

    resp = client.get(f"/parade/history/{snap_id}")
    assert resp.status_code == 200
    assert b"verbatim snapshot body" in resp.data
    # Copying a past state must not re-archive it: the button is a plain copy.
    assert b"data-copy" in resp.data
    assert b"data-snapshot-url" not in resp.data


def test_history_detail_404_for_unknown_id(app, client, make_person):
    make_person(username="hist_404_viewer")
    login(client, "hist_404_viewer")
    resp = client.get("/parade/history/999999")
    assert resp.status_code == 404


def test_nav_shows_past_states_link(app, client, make_person):
    make_person(username="hist_nav_viewer")
    login(client, "hist_nav_viewer")
    home = client.get("/").data
    assert b'href="/parade/history"' in home


# --- T5: copy button carries the snapshot data seam on live pages -----------

def test_parade_pages_copy_button_carries_snapshot_attrs(app, client, make_person):
    # Attribute presence is the testable seam for the fire-and-forget copy JS
    # (there is no JS runner in the repo): the live pages carry data-snapshot-*,
    # and the history detail (tested above) deliberately does not.
    make_person(username="snap_attr_viewer", display_name="Attr Viewer")
    login(client, "snap_attr_viewer")

    for path in ("/parade/morning", "/parade/roll-call"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert b'data-snapshot-url="/parade/snapshot"' in resp.data
        assert b"data-snapshot-variant=" in resp.data
        assert b"data-snapshot-cos=" not in resp.data  # only the COS page carries this

    cos = client.get("/parade/cos-message")
    assert cos.status_code == 200
    assert b'data-snapshot-url="/parade/snapshot"' in cos.data
    assert b'data-snapshot-variant="cos"' in cos.data
    assert b"data-snapshot-cos=" in cos.data
