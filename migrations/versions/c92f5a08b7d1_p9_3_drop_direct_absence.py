"""P9.3: drop direct_absence

Revision ID: c92f5a08b7d1
Revises: a5e7b301cc48
Create Date: 2026-07-26 10:30:00.000000

Owner directive 2026-07-26: regulars are not tracked in this app — their
off/leave is keyed into the external ARCTIC FOE system, so a regular appears in
current strength unless an MC/other status says otherwise. The drop is
deliberate and owner-sanctioned; downgrade() recreates the table (with its two
check constraints and both indexes) exactly as 4a3f82f8e295 built it — rows are
not recoverable, only the shape.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c92f5a08b7d1'
down_revision = 'a5e7b301cc48'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('direct_absence', schema=None) as batch_op:
        batch_op.drop_index('ix_direct_absence_range')
        batch_op.drop_index(batch_op.f('ix_direct_absence_person_id'))

    op.drop_table('direct_absence')


def downgrade():
    op.create_table('direct_absence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('type', sa.Enum('LEAVE', 'OTHER', name='direct_absence_type'), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('day_part', sa.Enum('FULL', 'AM', 'PM', name='day_part'), nullable=False),
    sa.Column('remarks', sa.String(length=300), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("day_part = 'FULL' OR start_date = end_date", name='ck_direct_absence_half_day_single_day'),
    sa.CheckConstraint('start_date <= end_date', name='ck_direct_absence_date_order'),
    sa.ForeignKeyConstraint(['created_by_id'], ['person.id'], ),
    sa.ForeignKeyConstraint(['person_id'], ['person.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('direct_absence', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_direct_absence_person_id'), ['person_id'], unique=False)
        batch_op.create_index('ix_direct_absence_range', ['start_date', 'end_date'], unique=False)
