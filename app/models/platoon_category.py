"""Platoon seniority categories — owner decision (ee) 2026-07-30.

Which platoon sits in which category (STC/Senior/Junior/Baby) is keyed data,
not code: the unit renumbers as batches ORD, so the People page sections and
the COS-pool carve-out both read these four rows. One row per category, created
once and edited forever — `platoon_service.ensure_rows` self-heals a fresh DB.
"""
from app.domain.types import PlatoonCategory
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class PlatoonCategorySetting(db.Model):
    """One row per category. `platoon` NULL means the category holds no platoon
    (with 3 platoons over 4 categories, one always does); the UNIQUE column is
    the DB-level guarantee that a platoon never sits in two categories.
    `in_cos_pool` off carves that platoon's people out of the COS auto-pick pool
    — the PS is untouched by construction, being CDO/S-eligible, not COS."""

    __tablename__ = "platoon_category"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(
        db.Enum(PlatoonCategory, values_callable=_values, name="platoon_category"),
        nullable=False,
        unique=True,
    )
    platoon = db.Column(db.Integer, nullable=True, unique=True)
    in_cos_pool = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self):
        return f"<PlatoonCategorySetting {self.category.value} platoon={self.platoon}>"
