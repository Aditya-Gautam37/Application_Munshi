"""Bill service tests — munshi/pg/services/bill_service.py, a port of
new_bill()'s business logic (app.py ~2461-2564). GST math itself
(compute_gst_split) is imported unchanged from munshi/utils/gst.py and
already covered by tests/test_smoke.py's reverse-charge/same-state/
inter-state cases — these tests only assert create_bill() calls through to
it correctly and wires numbering/linking correctly, not re-verify the tax
math.

Skips unless DATABASE_URL is set (see tests/conftest.py's pg_session fixture).
"""
import uuid
from datetime import date

from sqlalchemy import delete, text

from munshi.pg.models import LedgerEntry, Organization
from munshi.pg.services.bill_service import create_bill
from munshi.pg.services.organization_service import create_organization
from munshi.utils.gst import compute_gst_split


def _new_org(session, label):
    suffix = uuid.uuid4().hex[:8]
    org = create_organization(session, name=f'{label} {suffix}')
    session.commit()
    return org.id, suffix


def _cleanup(session, org_id):
    session.rollback()
    session.execute(text('RESET ROLE'))
    session.execute(delete(Organization).where(Organization.id == org_id))
    session.commit()


def test_create_bill_allocates_number_and_computes_gst(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    org_id, suffix = _new_org(session, 'Bill Service Test')

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        bill1 = create_bill(
            session, org_id,
            deliveries=[{'value_of_supply': '10000'}, {'value_of_supply': '5000'}],
            bill_date=date.today(),
            recipient_name=f'GST Test Client {suffix}',
            state_code='09', place_of_supply='09',   # same state -> CGST+SGST
            gst_pct=5, reverse_charge=False, supplier_state='09',
        )
        session.commit()

        assert bill1.bill_no == 'JL-0001'
        assert float(bill1.taxable_value) == 15000.0

        expected = compute_gst_split(15000, 5, '09', '09', False)
        assert float(bill1.cgst_amount) == expected['cgst_amount']
        assert float(bill1.sgst_amount) == expected['sgst_amount']
        assert float(bill1.igst_amount) == 0.0
        assert float(bill1.total_amount) == expected['grand_total']

        # A second bill in the same org gets the next sequential number.
        pg_database.set_tenant_context(session, org_id=org_id)
        bill2 = create_bill(
            session, org_id,
            deliveries=[{'value_of_supply': '1000'}],
            bill_date=date.today(),
            recipient_name=f'GST Test Client {suffix}',
            reverse_charge=True,
        )
        session.commit()
        assert bill2.bill_no == 'JL-0002'
    finally:
        _cleanup(session, org_id)


def test_create_bill_links_to_source_ledger_entry(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    org_id, suffix = _new_org(session, 'Bill Ledger Link Test')

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        entry = LedgerEntry(organization_id=org_id, entry_date=date.today(), freight=7000)
        session.add(entry)
        session.commit()
        le_id = entry.id

        pg_database.set_tenant_context(session, org_id=org_id)
        bill = create_bill(
            session, org_id,
            deliveries=[{'value_of_supply': '7000'}],
            bill_date=date.today(),
            recipient_name=f'Link Test Client {suffix}',
            reverse_charge=True,
            from_ledger_id=le_id,
        )
        session.commit()

        assert bill.ledger_entry_id == le_id

        pg_database.set_tenant_context(session, org_id=org_id)
        refreshed = session.get(LedgerEntry, le_id)
        assert refreshed.bill_id == bill.id
    finally:
        _cleanup(session, org_id)
