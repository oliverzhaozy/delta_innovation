"""Platoon-category storage (owner decision (ee) 2026-07-30): fetch/create the
four category rows and write the S3's mapping in one transaction.

The rules live in domain/platoons.py; this module only owns the rows. The
default shipped mapping (1=Junior, 2=STC excluded, 3=Senior) is the MIGRATION's
seed, not this module's — `ensure_rows` deliberately creates platoon-less rows
so a fresh DB (tests, a new instance) excludes nobody until someone keys it.
"""
from sqlalchemy.exc import IntegrityError

from app.domain import platoons
from app.domain.types import PlatoonCategory
from app.extensions import db
from app.models import PlatoonCategorySetting


class DuplicatePlatoon(Exception):
    """A platoon sits in exactly one category — friendly error (the UNIQUE
    column is the backstop, not the check)."""


def ensure_rows() -> None:
    """Create any missing category row. Why: schemas built by `create_all` carry
    no migration seed, so every read path would otherwise have to cope with a
    partial table; self-healing to a sane state keeps `category_rows` total.

    STC arrives excluded from the COS pool (the unit's convention) but with NO
    platoon, so a fresh DB carves nobody out until the mapping is keyed."""
    existing = {row.category for row in db.session.query(PlatoonCategorySetting).all()}
    missing = [category for category in PlatoonCategory if category not in existing]
    if not missing:
        return
    for category in missing:
        db.session.add(
            PlatoonCategorySetting(
                category=category,
                platoon=None,
                in_cos_pool=category is not PlatoonCategory.STC,
            )
        )
    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent first touch won the UNIQUE(category) race; its rows are
        # the truth. Never a pre-check SELECT.
        db.session.rollback()


def category_rows() -> list:
    """The four rows in PlatoonCategory order — the one shape callers read."""
    ensure_rows()
    rows = {row.category: row for row in db.session.query(PlatoonCategorySetting).all()}
    return [rows[category] for category in PlatoonCategory]


def set_categories(assignments) -> None:
    """Write the mapping in ONE transaction. `assignments` maps PlatoonCategory
    -> (platoon or None, in_cos_pool) and normally names all four categories.
    Raises DuplicatePlatoon rather than letting two categories claim a platoon.
    """
    chosen = [platoon for platoon, _in_pool in assignments.values() if platoon is not None]
    if len(chosen) != len(set(chosen)):
        raise DuplicatePlatoon(
            "Each platoon can sit in only one category — two categories were "
            "given the same platoon."
        )
    rows = {row.category: row for row in category_rows()}
    # Clear the platoons being reassigned in a statement of their own: `platoon`
    # is UNIQUE, so swapping two categories' platoons would violate the index
    # mid-flush if the new values were written straight over the old ones.
    for category in assignments:
        rows[category].platoon = None
    db.session.flush()
    for category, (platoon, in_cos_pool) in assignments.items():
        rows[category].platoon = platoon
        rows[category].in_cos_pool = in_cos_pool
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise DuplicatePlatoon("Each platoon can sit in only one category.")


def cos_exclusions() -> dict:
    """Excluded platoon -> the category excluding it (for the warning wording)."""
    return platoons.cos_exclusions(category_rows())


def cos_excluded_platoons() -> frozenset:
    return platoons.cos_excluded_platoons(category_rows())
