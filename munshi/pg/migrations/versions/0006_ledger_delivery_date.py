"""add ledger_entries.delivery_date

Real gap found while porting ledger_pod() (POD marking + settlement
adjustments) to Postgres — SQLite's ledger_entries has a `delivery_date`
column (added via app.py's _add_column_if_missing(), same as the
settlement fields ported in migration 0002) that was never carried over to
the Postgres model. Also added to ledger_entries_archive so the Recycle
Bin's archive/restore round-trip (munshi/pg/services/recycle_bin_service.py,
which copies only columns present on BOTH the live and archive tables)
doesn't silently drop it.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ledger_entries', sa.Column('delivery_date', sa.Date))
    op.add_column('ledger_entries_archive', sa.Column('delivery_date', sa.Date))


def downgrade():
    op.drop_column('ledger_entries_archive', 'delivery_date')
    op.drop_column('ledger_entries', 'delivery_date')
