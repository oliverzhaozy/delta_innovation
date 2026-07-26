"""P9.5: remap COURSE statuses to OTHER (type removed)

Revision ID: b4d70e3f1a29
Revises: c92f5a08b7d1
Create Date: 2026-07-26 10:40:00.000000

Hand-written data migration, no DDL (precedent: f31c09a7d5e2). On SQLite the
enum column is a plain VARCHAR, so a removed enum member leaves old rows
readable by SQL but a ValueError on ORM load. Owner directive 2026-07-26: ON
COURSE derives solely from TP calendar events labelled TpLabel.ON_COURSE, so the
keyed COURSE status is gone. Remap stored rows to OTHER, preserving each row's
own in_camp flag and keeping the original meaning by writing the old label into
empty remarks (a remark-less course used to render "(ON COURSE)" from the type
label; after the remap the remark carries that text instead).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b4d70e3f1a29'
down_revision = 'c92f5a08b7d1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE status_entry "
        "SET remarks = COALESCE(NULLIF(remarks, ''), 'On course'), type = 'OTHER' "
        "WHERE type = 'COURSE'"
    )


def downgrade():
    # Lossy by design, matching the f31c09a7d5e2 precedent: which OTHER rows were
    # courses is only recoverable from remarks text, so there is nothing safe to
    # undo. (A restored course is now a TP calendar event, not a status row.)
    pass
