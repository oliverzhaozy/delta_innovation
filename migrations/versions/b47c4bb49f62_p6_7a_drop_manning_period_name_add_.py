"""P6.7a: drop manning_period.name; add manning_slot.is_manual

Revision ID: b47c4bb49f62
Revises: c5b8a2d17e64
Create Date: 2026-07-28 19:09:29.757759

Owner directive 2026-07-28: a manning period is identified by its dates alone,
so the optional `name` handle is gone; dropping the column destroys those
strings and is deliberate and owner-approved.

`is_manual` prepares auto-generation, mirroring the duty roster: the generator
replaces only its own rows. Every row that exists today came from the manual
assign path, so the column is added with a server_default of 1 to backfill
them True and the default is then dropped — the model supplies the value on
every insert, so the schema must not quietly decide it.

Autogenerate also proposed a status_entry.type VARCHAR->Enum alter; that is
SQLite reporting its own storage type for an unchanged enum column, not a
schema change, and is deliberately not carried here.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b47c4bb49f62'
down_revision = 'c5b8a2d17e64'
branch_labels = None
depends_on = None


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
    # existed — aborts having touched nothing and can simply be re-run. Once a
    # batch has started, an abort cannot fully undo itself: pysqlite defers
    # BEGIN until the first DML, so the batch's opening CREATE TABLE
    # _alembic_tmp_… commits outside the transaction and survives the rollback,
    # and the retry then dies on "table _alembic_tmp_manning_period already
    # exists" until someone drops it by hand.
    _assert_no_manning_slot_orphans("before the rebuild")

    # SQLite drops a column by rebuilding the table, and DROP TABLE on the old
    # manning_period copy trips FK enforcement whenever manning_slot rows point
    # at it — so FKs are off for the DDL below, per SQLite's documented ALTER
    # TABLE procedure, and the scoped foreign_key_check further down is what
    # replaces the enforcement that was lifted.
    #
    # Both pragmas run inside autocommit_block(): SQLite SILENTLY IGNORES
    # PRAGMA foreign_keys inside a transaction, and the batch copy leaves one
    # open. Without it the restore is a no-op and every later revision of the
    # same `flask db upgrade` run — DEPLOY.md applies all pending revisions on
    # ONE connection — would inherit FK enforcement disabled.
    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table('manning_period', schema=None) as batch_op:
        batch_op.drop_column('name')

    with op.batch_alter_table('manning_slot', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'is_manual', sa.Boolean(), nullable=False, server_default=sa.text('1'),
        ))

    with op.batch_alter_table('manning_slot', schema=None) as batch_op:
        batch_op.alter_column(
            'is_manual', existing_type=sa.Boolean(), existing_nullable=False,
            server_default=None,
        )

    # The rebuilds ran with enforcement lifted, so prove they left no dangling
    # reference instead of trusting them. This runs before the restore below,
    # while everything above is still uncommitted: the version stays on
    # c5b8a2d17e64 with `name` intact rather than shipping a corrupt database.
    _assert_no_manning_slot_orphans("after the rebuild")

    # Restoring enforcement goes LAST because autocommit_block() commits the
    # pending transaction: every statement above is still rollback-able when
    # the check runs, so a failure leaves the database on c5b8a2d17e64 with
    # `name` intact and the migration retryable. Nothing but the pragma follows
    # the commit.
    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys=ON")


def downgrade():
    with op.batch_alter_table('manning_slot', schema=None) as batch_op:
        batch_op.drop_column('is_manual')

    with op.batch_alter_table('manning_period', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.VARCHAR(length=80), nullable=True))
