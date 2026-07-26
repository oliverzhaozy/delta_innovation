"""P9.1: drop parade_override

Revision ID: 7f1c04ab92de
Revises: 463cd65fb6d8
Create Date: 2026-07-26 10:10:00.000000

Owner directive 2026-07-26: the parade state is a fully derived document — the
drag-and-drop recategorization layer is gone, so its table goes with it. The
drop is deliberate and owner-sanctioned; downgrade() recreates the table exactly
as 463cd65fb6d8 built it (rows are not recoverable, only the shape).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f1c04ab92de'
down_revision = '463cd65fb6d8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('parade_override', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_parade_override_date'))

    op.drop_table('parade_override')


def downgrade():
    op.create_table('parade_override',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('variant', sa.Enum('COS_MESSAGE', 'ROLL_CALL', 'MORNING', name='parade_variant'), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('target_category', sa.Enum('current_strength', 'others_in_camp', 'stay_out', 'leave', 'off_oil', 'on_course', 'mc', 'others', name='override_category'), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['person.id'], ),
    sa.ForeignKeyConstraint(['person_id'], ['person.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('date', 'variant', 'person_id', name='uq_parade_override_slot')
    )
    with op.batch_alter_table('parade_override', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_parade_override_date'), ['date'], unique=False)
