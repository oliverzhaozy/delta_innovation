"""person.meals_opt_in flag

Revision ID: 6c87a5db7fc9
Revises: b47c4bb49f62
Create Date: 2026-07-29 22:44:33.584671

Owner decision (bb) 2026-07-29 revises (j): meal indents cover every NSF plus
the regulars who individually choose to eat in camp. (Autogenerate's spurious
status_entry VARCHAR/Enum diff — the known SQLite artifact — was stripped by
hand.)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6c87a5db7fc9'
down_revision = 'b47c4bb49f62'
branch_labels = None
depends_on = None


def upgrade():
    # Plain ALTER TABLE ADD COLUMN, no batch: batch mode recreates the table,
    # and DROP TABLE person trips the foreign_keys pragma (every table points
    # here). server_default backfills existing rows for the NOT NULL column;
    # new rows use the model's default=False. (Autogenerate omits this.)
    op.add_column(
        'person',
        sa.Column('meals_opt_in', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('person', 'meals_opt_in')
