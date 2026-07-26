"""P9.2: drop parade_snapshot

Revision ID: a5e7b301cc48
Revises: 7f1c04ab92de
Create Date: 2026-07-26 10:20:00.000000

Owner directive 2026-07-26: the past-states archive goes — a parade document is
always re-derived, so there is nothing to freeze on Copy. The drop is deliberate
and owner-sanctioned; downgrade() recreates the table exactly as 4b9cc2165c12
built it (rows are not recoverable, only the shape).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a5e7b301cc48'
down_revision = '7f1c04ab92de'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('parade_snapshot', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_parade_snapshot_date'))

    op.drop_table('parade_snapshot')


def downgrade():
    op.create_table('parade_snapshot',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('variant', sa.Enum('COS_MESSAGE', 'ROLL_CALL', 'MORNING', name='parade_variant'), nullable=False),
    sa.Column('rendered_text', sa.Text(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['person.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('parade_snapshot', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_parade_snapshot_date'), ['date'], unique=False)
