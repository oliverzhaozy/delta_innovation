"""P10.3 (was P8.5) — parade_override service wiring.

These pin the stored-override path through the ONE build pipeline: a drag
changes build_doc().text and lights has_overrides; no rows leave the raw render
byte-identical; the upsert is latest-wins; overrides are scoped to their exact
(date, variant); clearing restores the derivation; a stale override self-heals;
and — the meals pin (owner decision 6) — a morning drag flows into the S4 indent
because meal_service derives through the same build_doc.

The note half (owner revision 2026-07-30) is pinned here too: a fresh drag is
bare, a typed note renders into the copyable text through the one suffix
formatter, a re-drag wipes it, and a reason is never printed under a category
that already names one.
"""
from datetime import timedelta

from app.domain.dates import format_ddmmyy, today_sgt
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
        assert built.overrides == {}
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


# --- keyer-typed notes on a moved line (owner revision 2026-07-30) -----------

def test_typed_note_renders_into_the_copyable_text(app, make_person):
    make_person(username="ov_note1", display_name="Note One")
    make_person(username="ov_note2")
    with app.app_context():
        pid = _pid("ov_note1")
        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.MC, created_by_id=pid
        )
        db.session.commit()
        # A fresh drag is bare: the dragged person has no backing row to quote.
        assert parade_service.build_doc(TODAY, MORNING).doc.mc == ("PTE NOTE ONE",)

        end = TODAY + timedelta(days=1)
        assert parade_service.set_override_note(
            TODAY, MORNING, pid, reason=None, start=TODAY, end=end
        ) is True
        db.session.commit()

        built = parade_service.build_doc(TODAY, MORNING)
        line = f"PTE NOTE ONE ({format_ddmmyy(TODAY)} - {format_ddmmyy(end)})"
        assert built.doc.mc == (line,)
        assert line in built.text
        # The move the page will hang a note editor off carries the same note.
        assert built.overrides[pid].note.start == TODAY
        assert built.overrides[pid].note.end == end


def test_blank_note_clears_the_suffix_back_to_a_bare_line(app, make_person):
    make_person(username="ov_clr1", display_name="Clear One")
    make_person(username="ov_clr2")
    with app.app_context():
        pid = _pid("ov_clr1")
        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.MC, created_by_id=pid
        )
        parade_service.set_override_note(
            TODAY, MORNING, pid, reason=None, start=TODAY, end=TODAY
        )
        db.session.commit()
        assert f"PTE CLEAR ONE ({format_ddmmyy(TODAY)})" in parade_service.build_doc(
            TODAY, MORNING
        ).text

        parade_service.set_override_note(
            TODAY, MORNING, pid, reason=None, start=None, end=None
        )
        db.session.commit()
        built = parade_service.build_doc(TODAY, MORNING)
        assert built.doc.mc == ("PTE CLEAR ONE",)
        assert built.overrides[pid].note is None


def test_reason_prints_only_where_the_category_does_not_name_it(app, make_person):
    make_person(username="ov_rsn1", display_name="Reason One")
    make_person(username="ov_rsn2", display_name="Reason Two")
    with app.app_context():
        reasoned, plain = _pid("ov_rsn1"), _pid("ov_rsn2")
        parade_service.set_override(
            TODAY, MORNING, reasoned, OverrideCategory.OTHERS, created_by_id=reasoned
        )
        parade_service.set_override_note(
            TODAY, MORNING, reasoned, reason="HL", start=TODAY, end=TODAY
        )
        # MC already names the reason in its header, so a stored one is not
        # printed — the render-side guarantee, whatever a row happens to hold.
        parade_service.set_override(
            TODAY, MORNING, plain, OverrideCategory.MC, created_by_id=plain
        )
        parade_service.set_override_note(
            TODAY, MORNING, plain, reason="HL", start=TODAY, end=TODAY
        )
        db.session.commit()

        built = parade_service.build_doc(TODAY, MORNING)
        assert built.doc.others == (f"PTE REASON ONE (HL: {format_ddmmyy(TODAY)})",)
        assert built.doc.mc == (f"PTE REASON TWO ({format_ddmmyy(TODAY)})",)


def test_redrag_clears_the_typed_note(app, make_person):
    # Latest-wins consistency: the old note described the old target, so a second
    # drag starts bare rather than carrying a suffix nobody typed for it.
    make_person(username="ov_rd1", display_name="Redrag One")
    make_person(username="ov_rd2")
    with app.app_context():
        pid = _pid("ov_rd1")
        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.OTHERS, created_by_id=pid
        )
        parade_service.set_override_note(
            TODAY, MORNING, pid, reason="HL", start=TODAY, end=TODAY
        )
        db.session.commit()

        parade_service.set_override(
            TODAY, MORNING, pid, OverrideCategory.MC, created_by_id=pid
        )
        db.session.commit()

        row = db.session.query(ParadeOverride).one()
        assert row.target_category is OverrideCategory.MC
        assert (row.note_reason, row.note_start, row.note_end) == (None, None, None)
        assert parade_service.build_doc(TODAY, MORNING).doc.mc == ("PTE REDRAG ONE",)


def test_note_on_a_slot_that_was_never_dragged_writes_nothing(app, make_person):
    make_person(username="ov_noslot")
    with app.app_context():
        pid = _pid("ov_noslot")
        assert parade_service.set_override_note(
            TODAY, MORNING, pid, reason=None, start=TODAY, end=TODAY
        ) is False
        db.session.commit()
        assert db.session.query(ParadeOverride).count() == 0


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
