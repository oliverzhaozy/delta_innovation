"""Duty rework: drop the draft state, add is_manual, add duty_blocked_day

Revision ID: d3f81b6a27c9
Revises: a1c7e5d20f83
Create Date: 2026-07-27 12:00:00.000000

Owner directive 2026-07-27: a generated roster is live immediately, so the
PROPOSED/CONFIRMED two-step and its confirm stamp are gone. Dropping `state`,
`confirmed_by_id` and `confirmed_at` destroys data and is deliberate and
owner-approved; the backfill below carries the only fact still needed forward —
a CONFIRMED row was a human's decision, so it becomes `is_manual = 1` and
regeneration replans around it, while PROPOSED drafts become replaceable.

downgrade() restores the three columns exactly as ee80cb49ef02 built them and
re-derives `state` from `is_manual`; the confirm stamps are not recoverable.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3f81b6a27c9'
down_revision = 'a1c7e5d20f83'
branch_labels = None
depends_on = None


def upgrade():
    # Two batch blocks with the backfill between them: the column must hold a
    # value for every existing row before it can be made NOT NULL.
    with op.batch_alter_table('duty_assignment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_manual', sa.Boolean(), nullable=True))

    op.execute(
        "UPDATE duty_assignment SET is_manual = CASE WHEN state = 'CONFIRMED' THEN 1 ELSE 0 END"
    )

    with op.batch_alter_table('duty_assignment', schema=None) as batch_op:
        batch_op.alter_column('is_manual', existing_type=sa.Boolean(), nullable=False)
        batch_op.drop_column('confirmed_at')
        batch_op.drop_column('confirmed_by_id')
        batch_op.drop_column('state')

    op.create_table('duty_blocked_day',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['person.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('date')
    )


def downgrade():
    op.drop_table('duty_blocked_day')

    with op.batch_alter_table('duty_assignment', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'state',
            sa.Enum('PROPOSED', 'CONFIRMED', name='duty_state'),
            nullable=True,
        ))
        batch_op.add_column(sa.Column('confirmed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('confirmed_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            'fk_duty_assignment_confirmed_by_id_person', 'person',
            ['confirmed_by_id'], ['id'],
        )

    op.execute(
        "UPDATE duty_assignment SET state = CASE WHEN is_manual THEN 'CONFIRMED' ELSE 'PROPOSED' END"
    )

    with op.batch_alter_table('duty_assignment', schema=None) as batch_op:
        batch_op.alter_column(
            'state',
            existing_type=sa.Enum('PROPOSED', 'CONFIRMED', name='duty_state'),
            nullable=False,
        )
        batch_op.drop_column('is_manual')
