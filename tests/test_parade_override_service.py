"""P10.3 (was P8.5) — parade_override service wiring.

These pin the stored-override path through the ONE build pipeline: a drag
changes build_doc().text and lights has_overrides; no rows leave the raw render
byte-identical; the upsert is latest-wins; overrides are scoped to their exact
(date, variant); clearing restores the derivation; a stale override self-heals;
and — the meals pin (owner decision 6) — a morning drag flows into the S4 indent
because meal_service derives through the same build_doc.
"""
from datetime import timedelta

from app.domain.dates import today_sgt
from app.domain.types import OverrideCategory, ParadeVariant, Service
from app.extensions import db
from app.models import ParadeOverride, Person
from app.services import meal_service, parade_service

TODAY = today_sgt()
MORNING = ParadeVariant.MORNING
ROLL_CALL = ParadeVariant.ROLL_CALL


def _pid(username):
    return db.session.query(Person.id).filter_by(username=username).scalar()


def test_no_overrides_false_and_text_is_raw_render(app, make_person):
    make_person(username="ov_raw1")
    make_person(username="ov_raw2")
    with app.app_context():
        built = parade_service.build_doc(TODAY, MORNING)
        assert built.has_overrides is False
        # No override rows: build_doc's apply_overrides pass is identity, so the
        # text is exactly the raw presence-engine render (both present NSFs land
        # in CURRENT STRENGTH).
        assert "CURRENT STRENGTH: 2" in built.text
        assert "MC (0):" in built.text


def test_override_changes_text_and_clear_restores_byte_identical(app, make_person):
    make_person(username="ov_present1", display_name="Present One")
    make_person(username="ov_present2", display_name="Present Two")
    with app.app_context():
        baseline = parade_service.build_doc(TODAY, MORNING)
        assert baseline.has_overrides is False
        pid = _pid("ov_present1")

        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.MC, created_by_id=pid
        )
        db.session.commit()

        moved = parade_service.build_doc(TODAY, MORNING)
        assert moved.has_overrides is True
        assert moved.text != baseline.text
        assert "CURRENT STRENGTH: 1" in moved.text
        assert "MC (1):" in moved.text
        assert moved.doc.mc == ("PTE PRESENT ONE",)

        parade_service.clear_overrides(TODAY, MORNING)
        db.session.commit()

        restored = parade_service.build_doc(TODAY, MORNING)
        assert restored.has_overrides is False
        assert restored.text == baseline.text


def test_upsert_is_latest_wins_single_row(app, make_person):
    make_person(username="ov_lw1")
    make_person(username="ov_lw2")
    with app.app_context():
        pid = _pid("ov_lw1")
        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.MC, created_by_id=pid
        )
        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.LEAVE, created_by_id=pid
        )
        db.session.commit()

        rows = (
            db.session.query(ParadeOverride)
            .filter_by(date=TODAY, variant=MORNING, person_id=pid)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].target_category is OverrideCategory.LEAVE
        built = parade_service.build_doc(TODAY, MORNING)
        assert "LEAVE (1):" in built.text
        assert "MC (0):" in built.text


def test_no_cross_day_or_variant_leakage(app, make_person):
    make_person(username="ov_x1")
    make_person(username="ov_x2")
    with app.app_context():
        pid = _pid("ov_x1")
        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.MC, created_by_id=pid
        )
        db.session.commit()

        # Same variant, next day: no override.
        other_day = parade_service.build_doc(TODAY + timedelta(days=1), MORNING)
        assert other_day.has_overrides is False
        # Same day, different variant: no override.
        rc = parade_service.build_doc(TODAY, ROLL_CALL)
        assert rc.has_overrides is False


def test_cos_current_strength_override_drops_the_line(app, make_person):
    # D4 through the service: the COS message is built for tomorrow, and a
    # regular defaults to STAY OUT there — dragging onto "present" removes them.
    make_person(username="ov_cos_reg", display_name="Regular One",
                service=Service.REGULAR)
    make_person(username="ov_cos_nsf", display_name="Nsf One")
    tomorrow = TODAY + timedelta(days=1)
    with app.app_context():
        baseline = parade_service.build_doc(
            tomorrow, ParadeVariant.COS_MESSAGE, cos_display="SSG KEYER"
        )
        assert "REGULAR ONE" in baseline.text
        pid = _pid("ov_cos_reg")

        parade_service.set_override(
            tomorrow, ParadeVariant.COS_MESSAGE, pid,
            OverrideCategory.CURRENT_STRENGTH, created_by_id=pid,
        )
        db.session.commit()

        moved = parade_service.build_doc(
            tomorrow, ParadeVariant.COS_MESSAGE, cos_display="SSG KEYER"
        )
        assert moved.has_overrides is True
        assert "REGULAR ONE" not in moved.text
        assert "STAY OUT (0):" in moved.text

        parade_service.clear_overrides(tomorrow, ParadeVariant.COS_MESSAGE)
        db.session.commit()
        restored = parade_service.build_doc(
            tomorrow, ParadeVariant.COS_MESSAGE, cos_display="SSG KEYER"
        )
        assert restored.text == baseline.text


def test_meals_pin_morning_override_drops_indent_by_one(app, make_person):
    # Owner decision 6: overrides apply inside build_doc, the one pipeline, so
    # the S4 meal count inherits a drag. Moving a present NSF out of CURRENT
    # STRENGTH on the morning doc drops that day's indent by one.
    make_person(username="ov_meal1", display_name="Meal One")
    make_person(username="ov_meal2", display_name="Meal Two")
    with app.app_context():
        base, base_imb = meal_service.compute_for(TODAY)
        assert base_imb is None
        pid = _pid("ov_meal1")

        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.MC, created_by_id=pid
        )
        db.session.commit()

        after, after_imb = meal_service.compute_for(TODAY)
        assert after_imb is None
        assert after == base - 1
