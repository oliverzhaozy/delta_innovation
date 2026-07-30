"""decision (ee) — services/platoon_service.py: the four category rows, their
self-healing defaults, and the one-transaction write.

The rules are pinned in test_platoons_domain.py; this suite is the storage
contract — row creation on a migration-less schema, the duplicate-platoon
rejection, and the swap that a naive UPDATE order would break on the UNIQUE
column.
"""
import pytest

from app.domain.types import PlatoonCategory
from app.extensions import db
from app.models import PlatoonCategorySetting
from app.services import platoon_service


def mapping(**by_name):
    """{PlatoonCategory: (platoon, in_cos_pool)} from CATEGORY-NAME kwargs, each
    value either a platoon-or-None or a (platoon, in_cos_pool) pair."""
    assignments = {}
    for category in PlatoonCategory:
        value = by_name.get(category.name, None)
        assignments[category] = value if isinstance(value, tuple) else (value, True)
    return assignments


def stored():
    return {
        row.category: (row.platoon, row.in_cos_pool)
        for row in platoon_service.category_rows()
    }


# --- ensure_rows / category_rows -------------------------------------------------

def test_ensure_rows_creates_all_four_with_stc_excused(app):
    with app.app_context():
        platoon_service.ensure_rows()
        rows = db.session.query(PlatoonCategorySetting).all()
        assert {r.category for r in rows} == set(PlatoonCategory)
        # A migration-less schema must carve NOBODY out: STC arrives excused from
        # the COS pool but with no platoon, so the flag has nothing to act on.
        assert all(r.platoon is None for r in rows)
        assert {r.category: r.in_cos_pool for r in rows} == {
            PlatoonCategory.STC: False,
            PlatoonCategory.SENIOR: True,
            PlatoonCategory.JUNIOR: True,
            PlatoonCategory.BABY: True,
        }
        assert platoon_service.cos_excluded_platoons() == frozenset()


def test_ensure_rows_is_idempotent_and_never_overwrites(app):
    with app.app_context():
        platoon_service.set_categories(mapping(STC=(2, False), SENIOR=3, JUNIOR=1))
        platoon_service.ensure_rows()
        platoon_service.ensure_rows()
        assert db.session.query(PlatoonCategorySetting).count() == len(PlatoonCategory)
        assert stored()[PlatoonCategory.STC] == (2, False)


def test_category_rows_reads_in_enum_order(app):
    with app.app_context():
        assert [row.category for row in platoon_service.category_rows()] == list(
            PlatoonCategory
        )


def test_category_rows_backfills_a_partially_seeded_table(app):
    with app.app_context():
        db.session.add(
            PlatoonCategorySetting(
                category=PlatoonCategory.SENIOR, platoon=3, in_cos_pool=True
            )
        )
        db.session.commit()
        rows = platoon_service.category_rows()
        assert len(rows) == len(PlatoonCategory)
        assert stored()[PlatoonCategory.SENIOR] == (3, True)


# --- set_categories --------------------------------------------------------------

def test_set_categories_writes_the_default_shipped_mapping(app):
    with app.app_context():
        platoon_service.set_categories(mapping(STC=(2, False), SENIOR=3, JUNIOR=1))
        assert stored() == {
            PlatoonCategory.STC: (2, False),
            PlatoonCategory.SENIOR: (3, True),
            PlatoonCategory.JUNIOR: (1, True),
            PlatoonCategory.BABY: (None, True),
        }
        assert platoon_service.cos_excluded_platoons() == frozenset({2})
        assert platoon_service.cos_exclusions() == {2: PlatoonCategory.STC}


def test_set_categories_rejects_a_platoon_in_two_categories(app):
    with app.app_context():
        platoon_service.set_categories(mapping(STC=2, SENIOR=3, JUNIOR=1))
        with pytest.raises(platoon_service.DuplicatePlatoon):
            platoon_service.set_categories(mapping(STC=2, SENIOR=2, JUNIOR=1))
        # Rejected before any write: the old mapping stands.
        assert stored()[PlatoonCategory.SENIOR] == (3, True)


def test_set_categories_can_swap_two_platoons(app):
    # The UNIQUE(platoon) trap: writing the new values straight over the old ones
    # would collide mid-flush, so the service clears first. A swap is a normal
    # renumbering, not an error.
    with app.app_context():
        platoon_service.set_categories(mapping(STC=2, SENIOR=3, JUNIOR=1))
        platoon_service.set_categories(mapping(STC=2, SENIOR=1, JUNIOR=3))
        assert stored()[PlatoonCategory.SENIOR] == (1, True)
        assert stored()[PlatoonCategory.JUNIOR] == (3, True)


def test_set_categories_can_move_a_platoon_to_another_category(app):
    with app.app_context():
        platoon_service.set_categories(mapping(STC=(2, False), SENIOR=3, JUNIOR=1))
        # Platoon 2 moves from STC to Baby — STC must release it inside the same
        # transaction or the UNIQUE column would reject the write.
        platoon_service.set_categories(
            mapping(STC=(None, False), SENIOR=3, JUNIOR=1, BABY=2)
        )
        assert stored()[PlatoonCategory.STC] == (None, False)
        assert stored()[PlatoonCategory.BABY] == (2, True)
        # Baby is in the pool, so the move puts platoon 2 back in it.
        assert platoon_service.cos_excluded_platoons() == frozenset()


def test_set_categories_leaves_categories_it_does_not_name_alone(app):
    with app.app_context():
        platoon_service.set_categories(mapping(STC=(2, False), SENIOR=3, JUNIOR=1))
        platoon_service.set_categories({PlatoonCategory.BABY: (None, False)})
        assert stored()[PlatoonCategory.STC] == (2, False)
        assert stored()[PlatoonCategory.BABY] == (None, False)


def test_set_categories_toggles_the_pool_flag_without_moving_a_platoon(app):
    with app.app_context():
        platoon_service.set_categories(mapping(STC=(2, False), SENIOR=3, JUNIOR=1))
        platoon_service.set_categories(mapping(STC=(2, True), SENIOR=3, JUNIOR=1))
        assert platoon_service.cos_excluded_platoons() == frozenset()
