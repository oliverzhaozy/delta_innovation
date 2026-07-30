"""decision (ee): platoon_category table + default mapping

Revision ID: dcfcdd81bb97
Revises: 36238cd97b9f
Create Date: 2026-07-30 22:02:30.239716

Owner decision (ee) 2026-07-30: the three platoons group into seniority
categories (STC/Senior/Junior/Baby) and a category may be excused the COS pool.
The mapping is data, so the table ships with the unit's CURRENT arrangement
seeded — 1=Junior, 2=STC (excused COS), 3=Senior, Baby empty — rather than
leaving the People page blank until someone keys it. New table only, so no
batch mode is involved. (Autogenerate's spurious status_entry VARCHAR/Enum
diff — the known SQLite reflection artifact — was stripped by hand.)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dcfcdd81bb97'
down_revision = '36238cd97b9f'
branch_labels = None
depends_on = None


def upgrade():
    platoon_category = op.create_table(
        'platoon_category',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'category',
            sa.Enum('STC', 'Senior', 'Junior', 'Baby', name='platoon_category'),
            nullable=False,
        ),
        sa.Column('platoon', sa.Integer(), nullable=True),
        sa.Column('in_cos_pool', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category'),
        sa.UniqueConstraint('platoon'),
    )
    op.bulk_insert(
        platoon_category,
        [
            {'category': 'STC', 'platoon': 2, 'in_cos_pool': False},
            {'category': 'Senior', 'platoon': 3, 'in_cos_pool': True},
            {'category': 'Junior', 'platoon': 1, 'in_cos_pool': True},
            {'category': 'Baby', 'platoon': None, 'in_cos_pool': True},
        ],
    )


def downgrade():
    op.drop_table('platoon_category')
