"""challan schema fixes + recycle-bin archive tables

Two real schema bugs fixed (found by direct comparison against app.py's
init_db() and the actual AI-extraction data shape, both confirmed still
present as of this migration):
  1. challans.invoice_source_image / invoice_raw_extraction were declared
     in munshi/pg/models.py but never actually created by 0001_baseline.py.
  2. challans.gate_in_time / gate_out_time / expected_arrival were modeled
     as timestamptz, but the AI extraction prompt fills them with free-form
     handwriting-derived text ("10:30 AM", often blank), not parseable
     timestamps -- changed to text, matching SQLite. Safe: no challan rows
     exist in Postgres yet, nothing to convert.

Also adds the four Recycle Bin archive tables (bills_archive,
challans_archive, ledger_entries_archive, payments_archive) -- SQLite's
_ensure_archive_table() dynamically clones whatever columns each live
table currently has; there's no equivalent runtime introspection on the
Postgres/Alembic side, so these are explicit, hand-mirrored tables instead
(see munshi/pg/models.py's module comment above the four *Archive classes
for the full reasoning, including why they carry no FKs to sibling
business tables).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    # ── Challan fixes ──────────────────────────────────────────────────────
    op.add_column('challans', sa.Column('invoice_source_image', sa.Text))
    op.add_column('challans', sa.Column('invoice_raw_extraction', JSONB))

    op.alter_column('challans', 'gate_in_time', type_=sa.Text,
                     postgresql_using='gate_in_time::text')
    op.alter_column('challans', 'gate_out_time', type_=sa.Text,
                     postgresql_using='gate_out_time::text')
    op.alter_column('challans', 'expected_arrival', type_=sa.Text,
                     postgresql_using='expected_arrival::text')

    # ── Recycle bin archive tables ────────────────────────────────────────
    op.create_table(
        'bills_archive',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column('organization_id', UUID(as_uuid=True),
                   sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bill_no', sa.Text, nullable=False),
        sa.Column('bill_date', sa.Date),
        sa.Column('recipient_name', sa.Text),
        sa.Column('recipient_address', sa.Text),
        sa.Column('recipient_gstin', sa.Text),
        sa.Column('state_code', sa.Text),
        sa.Column('trip_type', sa.Text),
        sa.Column('vehicle_no', sa.Text),
        sa.Column('freight_type', sa.Text),
        sa.Column('delivery_month', sa.Text),
        sa.Column('client_name', sa.Text),
        sa.Column('total_amount', sa.Numeric),
        sa.Column('deliveries', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('ledger_entry_id', sa.BigInteger),
        sa.Column('client_paid', sa.Boolean),
        sa.Column('client_paid_date', sa.Date),
        sa.Column('client_paid_amount', sa.Numeric),
        sa.Column('client_paid_mode', sa.Text),
        sa.Column('client_paid_reference', sa.Text),
        sa.Column('hsn_sac', sa.Text),
        sa.Column('taxable_value', sa.Numeric),
        sa.Column('reverse_charge', sa.Boolean),
        sa.Column('place_of_supply', sa.Text),
        sa.Column('igst_pct', sa.Numeric),
        sa.Column('cgst_pct', sa.Numeric),
        sa.Column('sgst_pct', sa.Numeric),
        sa.Column('igst_amount', sa.Numeric),
        sa.Column('cgst_amount', sa.Numeric),
        sa.Column('sgst_amount', sa.Numeric),
        sa.Column('irn', sa.Text),
        sa.Column('irn_qr', sa.Text),
    )

    op.create_table(
        'challans_archive',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column('organization_id', UUID(as_uuid=True),
                   sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lr_no', sa.Text),
        sa.Column('challan_date', sa.Date),
        sa.Column('consignor_name', sa.Text),
        sa.Column('consignor_address', sa.Text),
        sa.Column('consignee_name', sa.Text),
        sa.Column('consignee_address', sa.Text),
        sa.Column('from_city_state', sa.Text),
        sa.Column('to_city_state', sa.Text),
        sa.Column('invoice_no', sa.Text),
        sa.Column('invoice_date', sa.Date),
        sa.Column('consignment_value', sa.Numeric),
        sa.Column('gst_number', sa.Text),
        sa.Column('no_of_articles', sa.Text),
        sa.Column('description', sa.Text),
        sa.Column('value_of_goods', sa.Numeric),
        sa.Column('weight_kg', sa.Numeric),
        sa.Column('del_no', sa.Text),
        sa.Column('shipment_no', sa.Text),
        sa.Column('cost_no', sa.Text),
        sa.Column('seal_no', sa.Text),
        sa.Column('driver_name', sa.Text),
        sa.Column('driver_mobile', sa.Text),
        sa.Column('truck_no', sa.Text),
        sa.Column('gate_in_time', sa.Text),
        sa.Column('gate_out_time', sa.Text),
        sa.Column('lane_transit_time', sa.Text),
        sa.Column('expected_arrival', sa.Text),
        sa.Column('source_image', sa.Text),
        sa.Column('raw_extraction', JSONB),
        sa.Column('confidence_json', JSONB),
        sa.Column('status', sa.Text),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('ledger_entry_id', sa.BigInteger),
        sa.Column('pod_doc_no', sa.Text),
        sa.Column('invoice_source_image', sa.Text),
        sa.Column('invoice_raw_extraction', JSONB),
    )

    op.create_table(
        'ledger_entries_archive',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column('organization_id', UUID(as_uuid=True),
                   sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('challan_id', sa.BigInteger),
        sa.Column('entry_date', sa.Date),
        sa.Column('gr_no', sa.Text),
        sa.Column('vehicle_no', sa.Text),
        sa.Column('station', sa.Text),
        sa.Column('shipment_no', sa.Text),
        sa.Column('trip_type', sa.Text),
        sa.Column('mt_qty', sa.Numeric),
        sa.Column('freight', sa.Numeric),
        sa.Column('advance_cash', sa.Numeric),
        sa.Column('advance_account', sa.Numeric),
        sa.Column('diesel', sa.Numeric),
        sa.Column('diesel_vendor_id', sa.BigInteger),
        sa.Column('transporter_id', sa.BigInteger),
        sa.Column('shortage', sa.Numeric),
        sa.Column('leakage', sa.Numeric),
        sa.Column('breakage', sa.Numeric),
        sa.Column('unloading', sa.Numeric),
        sa.Column('detention', sa.Numeric),
        sa.Column('toll_tax', sa.Numeric),
        sa.Column('excess_km', sa.Numeric),
        sa.Column('pod_received', sa.Boolean),
        sa.Column('pod_date', sa.Date),
        sa.Column('pod_image', sa.Text),
        sa.Column('paid', sa.Boolean),
        sa.Column('paid_date', sa.Date),
        sa.Column('paid_mode', sa.Text),
        sa.Column('paid_amount', sa.Numeric),
        sa.Column('paid_reference', sa.Text),
        sa.Column('remarks', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('bill_id', sa.BigInteger),
        sa.Column('weight_kg', sa.Numeric),
    )

    op.create_table(
        'payments_archive',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column('organization_id', UUID(as_uuid=True),
                   sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('party_type', sa.Text, nullable=False),
        sa.Column('party_key', sa.Text, nullable=False),
        sa.Column('payment_date', sa.Date, nullable=False),
        sa.Column('amount', sa.Numeric, nullable=False),
        sa.Column('mode', sa.Text),
        sa.Column('reference', sa.Text),
        sa.Column('notes', sa.Text),
        sa.Column('source', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('created_by', sa.Text),
    )


def downgrade():
    op.drop_table('payments_archive')
    op.drop_table('ledger_entries_archive')
    op.drop_table('challans_archive')
    op.drop_table('bills_archive')

    op.alter_column('challans', 'expected_arrival', type_=sa.DateTime(timezone=True),
                     postgresql_using='expected_arrival::timestamptz')
    op.alter_column('challans', 'gate_out_time', type_=sa.DateTime(timezone=True),
                     postgresql_using='gate_out_time::timestamptz')
    op.alter_column('challans', 'gate_in_time', type_=sa.DateTime(timezone=True),
                     postgresql_using='gate_in_time::timestamptz')

    op.drop_column('challans', 'invoice_raw_extraction')
    op.drop_column('challans', 'invoice_source_image')
