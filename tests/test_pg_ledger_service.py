"""Ledger service tests — munshi/pg/services/ledger_service.py, a port of
_ledger_balance() and ledger_paid() (app.py ~4821-4832, ~5209-5254).

test_ledger_balance_matches_formula needs no live database (pure function) —
runs unconditionally, no DATABASE_URL skip-guard. The rest are DB-backed
(pg_session fixture) and skip unless DATABASE_URL is set.
"""
import uuid
from datetime import date
from types import SimpleNamespace

from sqlalchemy import delete, text

from munshi.pg.models import LedgerEntry, Organization
from munshi.pg.services.ledger_service import ledger_balance, mark_ledger_paid
from munshi.pg.services.organization_service import create_organization
from munshi.pg.services.transporter_service import create_transporter


def test_ledger_balance_matches_formula():
    entry = SimpleNamespace(
        freight=10000, advance_cash=2000, advance_account=1000, diesel=500,
        shortage=100, leakage=0, breakage=0, unloading=0,
        detention=300, toll_tax=0, excess_km=0,
    )
    # 10000 - 2000 - 1000 - 500 - 100 + 300 = 6700
    assert ledger_balance(entry) == 6700.0

    empty = SimpleNamespace()  # every field missing -> getattr(..., None) -> 0
    assert ledger_balance(empty) == 0.0

    negative = SimpleNamespace(
        freight=1000, advance_cash=1500, advance_account=0, diesel=0,
        shortage=0, leakage=0, breakage=0, unloading=0,
        detention=0, toll_tax=0, excess_km=0,
    )
    assert ledger_balance(negative) == -500.0  # over-advanced trips can go negative


def _new_org_with_transporter(session, label):
    from munshi.pg import database as pg_database

    suffix = uuid.uuid4().hex[:8]
    org = create_organization(session, name=f'{label} {suffix}')
    session.commit()
    org_id = org.id

    pg_database.set_tenant_context(session, org_id=org_id)
    transporter = create_transporter(session, org_id, name=f'Test Transporter {suffix}')
    session.commit()
    return org_id, transporter.id


def _cleanup(session, org_id):
    session.rollback()
    session.execute(text('RESET ROLE'))
    session.execute(delete(Organization).where(Organization.id == org_id))
    session.commit()


def test_mark_ledger_paid_falsy_amount_falls_back_to_net(pg_session):
    """Documents the preserved SQLite quirk: paid_amount=0 does NOT record a
    zero-value auto-payment — it silently falls back to the computed net
    balance. Not fixed in this port; see ledger_service.py's module
    docstring for why."""
    from munshi.pg import database as pg_database

    session = pg_session
    org_id, transporter_id = _new_org_with_transporter(session, 'Ledger Paid Quirk Test')

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        entry = LedgerEntry(organization_id=org_id, transporter_id=transporter_id,
                             entry_date=date.today(), freight=5000, advance_cash=1000)
        session.add(entry)
        session.commit()
        le_id = entry.id
        expected_net = ledger_balance(entry)  # 4000

        pg_database.set_tenant_context(session, org_id=org_id)
        mark_ledger_paid(session, org_id, le_id, is_paid=True, paid_amount=0)
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        row = session.execute(
            text("SELECT amount FROM payments WHERE organization_id=:org "
                 "AND reference=:ref"),
            {'org': org_id, 'ref': f'auto-paid:ledger:{le_id}'},
        ).fetchone()
        assert row is not None
        assert float(row[0]) == expected_net
    finally:
        _cleanup(session, org_id)


def test_mark_ledger_paid_without_transporter_skips_auto_payment(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    suffix = uuid.uuid4().hex[:8]
    org = create_organization(session, name=f'Ledger No Transporter Test {suffix}')
    session.commit()
    org_id = org.id

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        entry = LedgerEntry(organization_id=org_id, transporter_id=None,
                             entry_date=date.today(), freight=3000)
        session.add(entry)
        session.commit()
        le_id = entry.id

        pg_database.set_tenant_context(session, org_id=org_id)
        mark_ledger_paid(session, org_id, le_id, is_paid=True, paid_amount=3000)
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        row = session.execute(
            text("SELECT 1 FROM payments WHERE organization_id=:org AND reference=:ref"),
            {'org': org_id, 'ref': f'auto-paid:ledger:{le_id}'},
        ).fetchone()
        assert row is None  # no transporter -> no auto-payment row, no error
    finally:
        _cleanup(session, org_id)


def test_mark_ledger_paid_unmark_removes_auto_payment(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    org_id, transporter_id = _new_org_with_transporter(session, 'Ledger Unmark Test')

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        entry = LedgerEntry(organization_id=org_id, transporter_id=transporter_id,
                             entry_date=date.today(), freight=6000)
        session.add(entry)
        session.commit()
        le_id = entry.id
        ref = f'auto-paid:ledger:{le_id}'

        pg_database.set_tenant_context(session, org_id=org_id)
        mark_ledger_paid(session, org_id, le_id, is_paid=True, paid_amount=6000)
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        assert session.execute(
            text('SELECT 1 FROM payments WHERE organization_id=:org AND reference=:ref'),
            {'org': org_id, 'ref': ref},
        ).fetchone() is not None

        pg_database.set_tenant_context(session, org_id=org_id)
        mark_ledger_paid(session, org_id, le_id, is_paid=False)
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        assert session.execute(
            text('SELECT 1 FROM payments WHERE organization_id=:org AND reference=:ref'),
            {'org': org_id, 'ref': ref},
        ).fetchone() is None
    finally:
        _cleanup(session, org_id)
