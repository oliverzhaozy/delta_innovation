"""Overseas approval flow, hard-delete retract

Revision ID: c5b8a2d17e64
Revises: d3f81b6a27c9
Create Date: 2026-07-28 12:00:00.000000

Owner directive 2026-07-28: travel declarations get a PC-only approval step and
stop being history — retract deletes the row, and a row whose end_date has
passed is deleted on the next page load. This reverses P2.1's "rows are never
deleted, retract sets cancelled_at".

The data pass below is DESTRUCTIVE and deliberate: retracted rows and rows that
already ended are removed outright (they have no consumer left under the new
semantics), and every survivor is backfilled to APPROVED because it was live
under the old no-approval regime — nobody should have to re-approve travel that
was already declared and accepted.

downgrade() restores the schema only. The deleted rows are gone for good.
"""
import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5b8a2d17e64'
down_revision = 'd3f81b6a27c9'
branch_labels = None
depends_on = None

_STATUS = sa.Enum('PENDING', 'APPROVED', 'REJECTED', name='declaration_status')


def upgrade():
    # First batch is add_column/create_index only, so SQLite takes it as plain
    # ALTERs; the server_default is what lets a NOT NULL column land on a
    # populated table, and it is dropped again in the second batch.
    with op.batch_alter_table('overseas_declaration', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('status', _STATUS, nullable=False, server_default='PENDING')
        )
        batch_op.add_column(sa.Column('pc_actor_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pc_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('remarks', sa.String(length=300), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_overseas_declaration_status'), ['status'], unique=False
        )

    # Expiry is measured against the host's today — migrations run on the
    # SGT-configured host, the same clock domain.dates.today_sgt() reads.
    today = datetime.date.today().isoformat()
    op.execute("DELETE FROM overseas_declaration WHERE cancelled_at IS NOT NULL")
    op.execute(f"DELETE FROM overseas_declaration WHERE end_date < '{today}'")
    op.execute("UPDATE overseas_declaration SET status = 'APPROVED'")

    with op.batch_alter_table('overseas_declaration', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_overseas_declaration_pc_actor_id_person', 'person',
            ['pc_actor_id'], ['id'],
        )
        batch_op.alter_column('status', existing_type=_STATUS, server_default=None)
        batch_op.drop_column('cancelled_at')


def downgrade():
    # Schema only: the rows this migration deleted are not recoverable, and the
    # PC decisions recorded in the dropped columns go with them.
    with op.batch_alter_table('overseas_declaration', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cancelled_at', sa.DateTime(), nullable=True))
        batch_op.drop_constraint(
            'fk_overseas_declaration_pc_actor_id_person', type_='foreignkey'
        )
        batch_op.drop_index(batch_op.f('ix_overseas_declaration_status'))
        batch_op.drop_column('remarks')
        batch_op.drop_column('pc_at')
        batch_op.drop_column('pc_actor_id')
        batch_op.drop_column('status')
