"""drop FK enforcement on the bill<->ledger_entry<->challan soft links

Real bug found while wiring the Recycle Bin's delete routes (tests/
test_pg_recycle_bin.py): 0001_baseline.py put real, enforced FK constraints
on the bidirectional bill<->ledger_entry and challan<->ledger_entry links
(bills.ledger_entry_id, challans.ledger_entry_id, ledger_entries.bill_id,
ledger_entries.challan_id). But the product's own soft-delete design
(app.py's delete_bill()/ledger_delete()/challan_delete(), and the _RECYCLE
config's purge_null lists) deliberately leaves those links dangling for the
entire time a row sits in the Recycle Bin -- only PURGE nulls them, so that
a plain RESTORE gets the exact link back "for free" by re-inserting the
archived row at its original id. SQLite never enforced these as real FKs,
so that design worked there; Postgres's real FK constraints reject the
delete outright the moment ANY live row still points at the id being
archived (confirmed: deleting a ledger_entries row referenced by
bills.ledger_entry_id raises ForeignKeyViolation).

Nulling the link at delete time instead (to satisfy the FK) was considered
and rejected -- it would prematurely free e.g. a billed ledger trip back to
"Ready to Bill" the moment the bill is soft-deleted, not only once it's
actually purged, which is explicitly not what the UI promises (see
recycle_bin.html's purge confirmation copy: "its ledger trips will return
to Ready to Bill" -- said only about permanent deletion).

So these four constraints are dropped, matching the precedent already set
for the *_archive tables (see 0004's docstring / munshi/pg/models.py's
Recycle Bin section): these cross-references are app-managed "soft" FKs,
not DB-enforced ones. All other FKs (organization_id everywhere,
diesel_vendor_id, transporter_id, extraction_id) are untouched -- this is
scoped to exactly the four soft-link columns the Recycle Bin's purge_null
logic already treats as advisory.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24
"""
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('fk_bills_ledger_entry_id', 'bills', type_='foreignkey')
    op.drop_constraint('fk_challans_ledger_entry_id', 'challans', type_='foreignkey')
    op.drop_constraint('ledger_entries_bill_id_fkey', 'ledger_entries', type_='foreignkey')
    op.drop_constraint('ledger_entries_challan_id_fkey', 'ledger_entries', type_='foreignkey')


def downgrade():
    op.create_foreign_key('ledger_entries_challan_id_fkey', 'ledger_entries', 'challans', ['challan_id'], ['id'])
    op.create_foreign_key('ledger_entries_bill_id_fkey', 'ledger_entries', 'bills', ['bill_id'], ['id'])
    op.create_foreign_key('fk_challans_ledger_entry_id', 'challans', 'ledger_entries', ['ledger_entry_id'], ['id'])
    op.create_foreign_key('fk_bills_ledger_entry_id', 'bills', 'ledger_entries', ['ledger_entry_id'], ['id'])
