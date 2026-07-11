"""UI-21: remap BRIEFING/SITE_TESTING status rows to OTHER (types removed)

Revision ID: f31c09a7d5e2
Revises: 001e8cfe780c
Create Date: 2026-07-11 22:05:00.000000

Hand-written data migration, no DDL: on SQLite the enum column is a plain
VARCHAR, so removed enum members leave old rows readable by SQL but a
ValueError on ORM load. Remap them to OTHER, preserving the row's own
in_camp flag, and keep the original meaning by writing the old label into
empty remarks (a remark-less briefing used to render "(BRIEFING)" from the
type label; after the remap the remark carries that text instead).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f31c09a7d5e2'
down_revision = '001e8cfe780c'
branch_labels = None
depends_on = None

_REMAP = {"BRIEFING": "Briefing", "SITE_TESTING": "Site testing"}


def upgrade():
    for old_value, label in _REMAP.items():
        op.execute(
            "UPDATE status_entry "
            f"SET remarks = COALESCE(NULLIF(remarks, ''), '{label}'), type = 'OTHER' "
            f"WHERE type = '{old_value}'"
        )


def downgrade():
    # The remap is lossy by design (which OTHER rows were briefings is only
    # recoverable from remarks text), so there is nothing safe to undo.
    pass
