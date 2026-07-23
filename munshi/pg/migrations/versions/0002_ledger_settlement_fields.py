"""ledger settlement adjustment fields

Adds the 7 POD-time settlement columns (shortage, leakage, breakage,
unloading, detention, toll_tax, excess_km) to ledger_entries. These exist in
the live SQLite app (added over time via app.py's _add_column_if_missing())
but were missing from the original 0001 baseline — without them,
payment_service._transporter_charges_net() and ledger_service.ledger_balance()
can't reproduce the SQLite balance formula, which reads all seven. Purely
additive, all server_default '0', matching the SQLite column defaults.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

_COLUMNS = ['shortage', 'leakage', 'breakage', 'unloading', 'detention', 'toll_tax', 'excess_km']


def upgrade():
    for col in _COLUMNS:
        op.add_column('ledger_entries', sa.Column(col, sa.Numeric, server_default='0'))


def downgrade():
    for col in reversed(_COLUMNS):
        op.drop_column('ledger_entries', col)
