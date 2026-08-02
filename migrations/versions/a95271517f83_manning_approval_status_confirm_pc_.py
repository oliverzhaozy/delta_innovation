"""manning approval: status + confirm/PC columns

Revision ID: a95271517f83
Revises: dcfcdd81bb97
Create Date: 2026-08-02 16:52:04.070218

Owner decision (ff) 2026-08-02: a manning period is built as a DRAFT, confirmed
by the S3, and approved by any PC. The columns below are the approval trail;
nothing about the document itself changes.

Every period that exists today was built under the no-approval regime and was
already the published record, so the backfill sets them all to APPROVED — the
same reasoning c5b8a2d17e64 used for surviving travel declarations. Nobody
should have to re-confirm a period that has already been pasted into WhatsApp.

Autogenerate also proposed a status_entry.type VARCHAR->Enum alter; that is
SQLite reporting its own storage type for an unchanged enum column, not a
schema change, and is deliberately not carried here (same call as b47c4bb49f62).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a95271517f83'
down_revision = 'dcfcdd81bb97'
branch_labels = None
depends_on = None

_STATUS = sa.Enum('DRAFT', 'PENDING', 'APPROVED', name='manning_status')


def _assert_no_manning_slot_orphans(stage):
    """Scoped to manning_slot on purpose: a bare `PRAGMA foreign_key_check`
    scans the WHOLE database and would abort this migration over an unrelated
    pre-existing orphan, blaming the manning rebuild for it. The pragma reports
    violations regardless of whether enforcement is currently on."""
    violations = op.get_bind().exec_driver_sql(
        "PRAGMA foreign_key_check('manning_slot')"
    ).fetchall()
    if violations:
        raise RuntimeError(
            f"manning_slot has dangling references {stage}: {violations}"
        )


def upgrade():
    # Checked BEFORE any DDL so the realistic failure — an orphan that already
    # existed — aborts having touched nothing and can simply be re-run (see
    # b47c4bb49f62 for why a half-started batch cannot undo itself here).
    _assert_no_manning_slot_orphans("before the rebuild")

    # The second batch's alter_column rebuilds manning_period, and DROP TABLE on
    # the old copy trips FK enforcement while manning_slot rows point at it — so
    # FKs go off for the DDL, per SQLite's documented ALTER TABLE procedure, and
    # the scoped foreign_key_check below replaces the enforcement that was
    # lifted. Both pragmas run inside autocommit_block(): SQLite SILENTLY
    # IGNORES PRAGMA foreign_keys inside a transaction, and the batch copy
    # leaves one open.
    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys=OFF")

    # First batch is add_column/create_index only, so SQLite takes it as plain
    # ALTERs; the server_default is what lets a NOT NULL column land on a
    # populated table, and it is dropped again in the second batch.
    with op.batch_alter_table('manning_period', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('status', _STATUS, nullable=False, server_default='DRAFT')
        )
        batch_op.add_column(sa.Column('confirmed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('confirmed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('pc_actor_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pc_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('remarks', sa.String(length=300), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_manning_period_status'), ['status'], unique=False
        )

    op.execute("UPDATE manning_period SET status = 'APPROVED'")

    with op.batch_alter_table('manning_period', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_manning_period_confirmed_by_id_person', 'person',
            ['confirmed_by_id'], ['id'],
        )
        batch_op.create_foreign_key(
            'fk_manning_period_pc_actor_id_person', 'person',
            ['pc_actor_id'], ['id'],
        )
        batch_op.alter_column('status', existing_type=_STATUS, server_default=None)

    # The rebuild ran with enforcement lifted, so prove it left no dangling
    # reference instead of trusting it. This runs while everything above is
    # still uncommitted: a failure leaves the database on dcfcdd81bb97.
    _assert_no_manning_slot_orphans("after the rebuild")

    # Restoring enforcement goes LAST because autocommit_block() commits the
    # pending transaction; nothing but the pragma follows it.
    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys=ON")


def downgrade():
    # Schema only: the confirm/approve trail recorded in these columns is lost.
    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table('manning_period', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_manning_period_pc_actor_id_person', type_='foreignkey'
        )
        batch_op.drop_constraint(
            'fk_manning_period_confirmed_by_id_person', type_='foreignkey'
        )
        batch_op.drop_index(batch_op.f('ix_manning_period_status'))
        batch_op.drop_column('remarks')
        batch_op.drop_column('pc_at')
        batch_op.drop_column('pc_actor_id')
        batch_op.drop_column('confirmed_at')
        batch_op.drop_column('confirmed_by_id')
        batch_op.drop_column('status')

    _assert_no_manning_slot_orphans("after the downgrade rebuild")

    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys=ON")
