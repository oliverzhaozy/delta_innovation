"""remove duty swap feature: drop duty_swap_log

Revision ID: ea8941c1b035
Revises: 73212be9e6c0
Create Date: 2026-07-24 21:53:56.657709

Owner request 2026-07-24: the swap feature and its log leave the duty page.
The table was verified empty before this migration was written, so the drop
loses no history. (Autogenerate's spurious status_entry VARCHAR/Enum diff —
the known SQLite artifact — was stripped by hand.)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ea8941c1b035'
down_revision = '73212be9e6c0'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('duty_swap_log')


def downgrade():
    op.create_table('duty_swap_log',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('person_a_id', sa.INTEGER(), nullable=False),
    sa.Column('person_b_id', sa.INTEGER(), nullable=False),
    sa.Column('date_a', sa.DATE(), nullable=False),
    sa.Column('date_b', sa.DATE(), nullable=False),
    sa.Column('duty', sa.VARCHAR(length=4), nullable=False),
    sa.Column('actor_id', sa.INTEGER(), nullable=False),
    sa.Column('at', sa.DATETIME(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['person.id'], ),
    sa.ForeignKeyConstraint(['person_a_id'], ['person.id'], ),
    sa.ForeignKeyConstraint(['person_b_id'], ['person.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
