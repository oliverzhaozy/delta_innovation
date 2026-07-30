"""decision (dd): drop person.is_active

Revision ID: 36238cd97b9f
Revises: 6c87a5db7fc9
Create Date: 2026-07-30 20:29:39.168855

Owner decision (dd) 2026-07-30: ORD/post-out hard-deletes the person and every
row referencing them (`person_service.delete_person`), so there is nothing left
for a soft-delete flag to mean. Data-dropping migration, explicitly approved.
(Autogenerate's spurious status_entry VARCHAR/Enum diff — the known SQLite
reflection artifact — was stripped by hand.)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '36238cd97b9f'
down_revision = '6c87a5db7fc9'
branch_labels = None
depends_on = None


def upgrade():
    # Plain ALTER TABLE DROP COLUMN, no batch — same reason the person flag
    # migrations avoid it: batch mode recreates the table, and DROP TABLE person
    # trips the foreign_keys pragma (every table points here). SQLite has
    # supported native DROP COLUMN since 3.35 (host is Debian 12 / 3.40).
    op.drop_column('person', 'is_active')


def downgrade():
    # server_default backfills the NOT NULL column for existing rows: anyone
    # still in the table is serving, which is exactly what is_active=True meant.
    op.add_column(
        'person',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
