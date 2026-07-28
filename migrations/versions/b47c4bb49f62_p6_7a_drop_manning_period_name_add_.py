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


def upgrade():
    # SQLite drops a column by rebuilding the table, and DROP TABLE on the old
    # manning_period copy trips FK enforcement whenever manning_slot rows point
    # at it — so FKs are off for that rebuild only, per SQLite's documented
    # ALTER TABLE procedure. The pragma is a silent no-op inside a transaction;
    # DDL here is non-transactional, and a no-op would fail the DROP loudly.
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table('manning_period', schema=None) as batch_op:
        batch_op.drop_column('name')
    op.execute("PRAGMA foreign_keys=ON")

    with op.batch_alter_table('manning_slot', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'is_manual', sa.Boolean(), nullable=False, server_default=sa.text('1'),
        ))

    with op.batch_alter_table('manning_slot', schema=None) as batch_op:
        batch_op.alter_column(
            'is_manual', existing_type=sa.Boolean(), existing_nullable=False,
            server_default=None,
        )


def downgrade():
    with op.batch_alter_table('manning_slot', schema=None) as batch_op:
        batch_op.drop_column('is_manual')

    with op.batch_alter_table('manning_period', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.VARCHAR(length=80), nullable=True))
