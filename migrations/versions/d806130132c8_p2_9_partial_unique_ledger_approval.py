"""p2_9_partial_unique_ledger_approval

Revision ID: d806130132c8
Revises: c231d5b9e1cd
Create Date: 2026-07-06 17:15:46.239100

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd806130132c8'
down_revision = 'c231d5b9e1cd'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite can't ALTER away a table-level constraint, so batch-recreate the
    # table without the old (source-inclusive) unique constraint, then add the
    # approval-scoped partial unique index in its place. The double-deduction
    # backstop now guards only LEAVE_APPROVAL debits; REVERSAL rows may repeat
    # (early-return amendment + a later cancel). Existing rows satisfy the new
    # index trivially — the old constraint already allowed at most one
    # LEAVE_APPROVAL row per (request, kind).
    with op.batch_alter_table('ledger_entry', schema=None) as batch_op:
        batch_op.drop_constraint('uq_ledger_request_source_kind', type_='unique')
    op.create_index(
        'uq_ledger_request_approval_kind',
        'ledger_entry',
        ['leave_request_id', 'kind'],
        unique=True,
        sqlite_where=sa.text("source = 'LEAVE_APPROVAL'"),
    )


def downgrade():
    op.drop_index('uq_ledger_request_approval_kind', table_name='ledger_entry')
    with op.batch_alter_table('ledger_entry', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_ledger_request_source_kind', ['leave_request_id', 'source', 'kind']
        )
