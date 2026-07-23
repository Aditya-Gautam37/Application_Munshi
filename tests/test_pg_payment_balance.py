"""Payment/balance regression tests — the split-brain-guard analog for the
Postgres port (mirrors tests/test_smoke.py's
test_client_payment_moves_both_sources_same_direction). Phase 2 only has one
source of truth (the `payments` table via get_party_balance()), so the
equivalent guard here is: recording a payment moves the balance by exactly
the payment amount, auto-payment upserts are idempotent, and — the core
invariant both munshi/pg/models.py's Payment docstring and app.py's
_transporter_charges_net()/_ledger_balance() comments call out —
get_party_balance('transporter', ...) agrees with summed ledger_balance()
term-by-term.

Skips unless DATABASE_URL is set (see tests/conftest.py's pg_session fixture).
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import delete, select, text

from munshi.pg.models import LedgerEntry, Organization
from munshi.pg.services.bill_service import create_bill
from munshi.pg.services.ledger_service import ledger_balance
from munshi.pg.services.organization_service import create_organization
from munshi.pg.services.payment_service import (
    auto_payment_remove,
    auto_payment_upsert,
    get_party_balance,
    record_manual_payment,
)
from munshi.pg.services.transporter_service import create_transporter


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


def test_client_payment_reduces_balance_by_exact_amount(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    org_id, suffix = _new_org(session, 'Payment Balance Test')
    client_name = f'Test Client {suffix}'

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        create_bill(
            session, org_id,
            deliveries=[{'value_of_supply': '10000'}],
            bill_date=date.today(),
            recipient_name=client_name,
            reverse_charge=True,  # zero tax, so total_amount == taxable_value == 10000 exactly
        )
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        balance_before = get_party_balance(session, org_id, 'client', client_name)
        assert balance_before == 10000.0

        record_manual_payment(session, org_id, 'client', client_name, amount=4000,
                               payment_date=date.today())
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        balance_after = get_party_balance(session, org_id, 'client', client_name)
        assert balance_after == 6000.0
        assert balance_before - balance_after == 4000.0
    finally:
        _cleanup(session, org_id)


def test_auto_payment_upsert_is_idempotent(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    org_id, suffix = _new_org(session, 'Auto Payment Idempotency Test')
    ref = f'auto-paid:ledger:{suffix}'

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        auto_payment_upsert(session, org_id, 'transporter', '999', 500, ref, when=date.today())
        auto_payment_upsert(session, org_id, 'transporter', '999', 800, ref, when=date.today())
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        rows = session.execute(
            text('SELECT amount FROM payments WHERE organization_id=:org AND reference=:ref'),
            {'org': org_id, 'ref': ref},
        ).fetchall()
        assert len(rows) == 1, f'expected exactly 1 row for ref {ref!r}, got {len(rows)}'
        assert float(rows[0][0]) == 800.0

        auto_payment_remove(session, org_id, ref)
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        rows = session.execute(
            text('SELECT amount FROM payments WHERE organization_id=:org AND reference=:ref'),
            {'org': org_id, 'ref': ref},
        ).fetchall()
        assert rows == []
    finally:
        _cleanup(session, org_id)


def test_transporter_balance_matches_summed_ledger_balance(pg_session):
    """The core invariant: get_party_balance('transporter', ...) (SQL
    aggregate in payment_service._transporter_charges_net) must agree with
    summing ledger_balance() (Python, per-row) across the same rows."""
    from munshi.pg import database as pg_database

    session = pg_session
    org_id, suffix = _new_org(session, 'Transporter Balance Test')

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        transporter = create_transporter(session, org_id, name=f'Test Transporter {suffix}')
        session.flush()
        transporter_id = transporter.id

        entries = [
            LedgerEntry(organization_id=org_id, transporter_id=transporter_id,
                        entry_date=date.today(), freight=10000, advance_cash=2000,
                        advance_account=1000, diesel=500, shortage=100, detention=300),
            LedgerEntry(organization_id=org_id, transporter_id=transporter_id,
                        entry_date=date.today(), freight=8000, diesel=200, toll_tax=150),
            LedgerEntry(organization_id=org_id, transporter_id=transporter_id,
                        entry_date=date.today(), freight=5000, breakage=50, excess_km=75),
        ]
        for e in entries:
            session.add(e)
        session.commit()

        pg_database.set_tenant_context(session, org_id=org_id)
        rows = session.execute(
            select(LedgerEntry).where(LedgerEntry.transporter_id == transporter_id)
        ).scalars().all()
        assert len(rows) == 3

        expected = sum(ledger_balance(e) for e in rows)
        actual = get_party_balance(session, org_id, 'transporter', transporter_id)
        assert actual == pytest.approx(expected)
    finally:
        _cleanup(session, org_id)
