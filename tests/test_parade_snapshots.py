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
