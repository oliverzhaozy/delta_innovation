"""P8.5 — parade_override service wiring.

These pin the stored-override path through the ONE build pipeline: a drag
changes build_doc().text and lights has_overrides; no rows leave the raw render
byte-identical; the upsert is latest-wins; overrides are scoped to their exact
(date, variant); clearing restores the derivation; a stale override self-heals;
and — the meals pin (owner decision 6) — a morning drag flows into the S4 indent
because meal_service derives through the same build_doc.
"""
from datetime import timedelta

from app.domain.dates import today_sgt
from app.domain.types import OverrideCategory, ParadeVariant
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


def test_stale_person_override_still_validates(app, make_person):
    make_person(username="ov_stale_active")
    make_person(username="ov_stale_gone", is_active=False)
    with app.app_context():
        active_pid = _pid("ov_stale_active")
        gone_pid = _pid("ov_stale_gone")  # inactive → never on the parade
        parade_service.set_override(
            TODAY, MORNING, gone_pid, OverrideCategory.MC, created_by_id=active_pid
        )
        db.session.commit()

        built = parade_service.build_doc(TODAY, MORNING)
        # The row exists (indicator lights), but the person isn't in the doc so
        # apply_overrides skips them — no imbalance, and the active person is
        # untouched in CURRENT STRENGTH.
        assert built.imbalance is None
        assert built.has_overrides is True
        assert "CURRENT STRENGTH: 1" in built.text
        assert "MC (0):" in built.text


def test_meals_pin_morning_override_drops_indent_by_one(app, make_person):
    # Owner decision 6: overrides apply inside build_doc, the one pipeline, so
    # the S4 meal counters inherit a drag. Moving a present NSF out of CURRENT
    # STRENGTH on the morning doc drops that day's in-camp indent by one.
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
        assert after.day_in_camp == base.day_in_camp - 1
        # The night counter (roll_call D+1, a different date+variant) is untouched.
        assert after.overnight == base.overnight
