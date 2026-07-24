"""RO: drop ro_standing_item and weekly_key_events (2026-07-24 revision)

Standing timeline items are removed outright and weekly key events are now
derived from the TP calendar at render time, so both tables (and any rows
in them) go — owner explicitly approved the data loss.

Revision ID: a41f09c2d7e3
Revises: d833c86e61e1
Create Date: 2026-07-24

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a41f09c2d7e3'
down_revision = 'd833c86e61e1'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('ro_standing_item')
    op.drop_table('weekly_key_events')


def downgrade():
    # Recreates the P5.2 shapes (b735f7b52bee); the dropped rows are gone.
    op.create_table('ro_standing_item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('time', sa.Time(), nullable=True),
    sa.Column('text', sa.String(length=200), nullable=False),
    sa.Column('recurrence', sa.Enum('DAILY', 'LAST_WORKING_DAY', name='ro_recurrence'), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('weekly_key_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('week_start', sa.Date(), nullable=False),
    sa.Column('mon', sa.String(length=300), nullable=False),
    sa.Column('tue', sa.String(length=300), nullable=False),
    sa.Column('wed', sa.String(length=300), nullable=False),
    sa.Column('thu', sa.String(length=300), nullable=False),
    sa.Column('fri', sa.String(length=300), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('week_start')
    )
