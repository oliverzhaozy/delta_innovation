"""person.duty_exempt flag

Revision ID: d833c86e61e1
Revises: ea8941c1b035
Create Date: 2026-07-24 22:00:02.746164

Owner decision 2026-07-24: a person-level carve-out from the COS/CDO-S duty
pools (first case: the 3WO P2IC). (Autogenerate's spurious status_entry
VARCHAR/Enum diff — the known SQLite artifact — was stripped by hand.)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd833c86e61e1'
down_revision = 'ea8941c1b035'
branch_labels = None
depends_on = None


def upgrade():
    # Plain ALTER TABLE ADD COLUMN, no batch: batch mode recreates the table,
    # and DROP TABLE person trips the foreign_keys pragma (every table points
    # here). server_default backfills existing rows for the NOT NULL column;
    # new rows use the model's default=False. (Autogenerate omits this.)
    op.add_column(
        'person',
        sa.Column('duty_exempt', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('person', 'duty_exempt')
