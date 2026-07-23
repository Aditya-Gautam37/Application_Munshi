"""Balances (AR/AP) and the `payments` single-source-of-truth — port of
app.py:1216-1310. `payments` is the ONLY table balances are computed from;
see munshi/pg/models.py's Payment docstring: the auto-payment-mirroring
convention (auto_payment_upsert/auto_payment_remove) "must be preserved
exactly."

Every query here filters by organization_id explicitly, in addition to
relying on RLS (set_tenant_context() must already be active on `session` —
this module never calls it itself, same convention as transporter_service).
This is deliberately stricter than Phase 1's transporter_service.py, which
relies on RLS alone: money-critical code gets defense-in-depth for free (one
extra WHERE clause) rather than trusting a single policy definition never
drifts. Matches munshi/pg/models.py's own module docstring stance of
enforcing tenant scoping "twice over."

Numeric/numeric-aggregate columns come back from psycopg as decimal.Decimal,
not float (despite the `Mapped[float | None]` type hints in models.py) —
every value pulled from a Numeric column or SUM(...) is explicitly
float()-cast before arithmetic, same discipline app.py's float(e[k] or 0)
pattern already enforces on the SQLite side.
"""
from datetime import date, datetime

from sqlalchemy import text

from munshi.pg.models import Payment

_PARTY_TYPES = ('client', 'transporter', 'diesel_vendor')


def _client_charges(session, organization_id, name):
    row = session.execute(
        text('SELECT COALESCE(SUM(total_amount),0) FROM bills '
             'WHERE organization_id=:org AND recipient_name=:name'),
        {'org': organization_id, 'name': name},
    ).fetchone()
    return float(row[0]) if row else 0.0


def _transporter_charges_net(session, organization_id, transporter_id):
    """Verbatim port of the SQLite formula, including its one asymmetry:
    `freight` itself is NOT COALESCE-wrapped (every other field is) — a NULL
    freight just excludes that row's contribution from SUM, it doesn't null
    the whole aggregate. Preserved as-is, not "fixed"."""
    row = session.execute(
        text('''
            SELECT COALESCE(SUM(freight - COALESCE(advance_cash,0) - COALESCE(advance_account,0)
                                - COALESCE(diesel,0)
                                - COALESCE(shortage,0) - COALESCE(leakage,0)
                                - COALESCE(breakage,0) - COALESCE(unloading,0)
                                + COALESCE(detention,0) + COALESCE(toll_tax,0)
                                + COALESCE(excess_km,0)), 0)
            FROM ledger_entries
            WHERE organization_id=:org AND transporter_id=:tid
        '''),
        {'org': organization_id, 'tid': transporter_id},
    ).fetchone()
    return float(row[0]) if row else 0.0


def _diesel_vendor_charges(session, organization_id, vendor_id):
    row = session.execute(
        text('SELECT COALESCE(SUM(diesel),0) FROM ledger_entries '
             'WHERE organization_id=:org AND diesel_vendor_id=:vid AND diesel > 0'),
        {'org': organization_id, 'vid': vendor_id},
    ).fetchone()
    return float(row[0]) if row else 0.0


def _payments_total(session, organization_id, party_type, party_key):
    row = session.execute(
        text('SELECT COALESCE(SUM(amount),0) FROM payments '
             'WHERE organization_id=:org AND party_type=:pt AND party_key=:pk'),
        {'org': organization_id, 'pt': party_type, 'pk': str(party_key)},
    ).fetchone()
    return float(row[0]) if row else 0.0


def get_party_balance(session, organization_id, party_type, party_key):
    """Positive = balance still pending (client owes us; we owe transporter/
    diesel vendor). Returns 0.0 for an unrecognized party_type, matching the
    SQLite original's silent-fallback behavior."""
    if party_type == 'client':
        charges = _client_charges(session, organization_id, party_key)
    elif party_type == 'transporter':
        charges = _transporter_charges_net(session, organization_id, int(party_key))
    elif party_type == 'diesel_vendor':
        charges = _diesel_vendor_charges(session, organization_id, int(party_key))
    else:
        return 0.0
    paid = _payments_total(session, organization_id, party_type, party_key)
    return charges - paid


def auto_payment_upsert(session, organization_id, party_type, party_key, amount, ref,
                         when=None, mode=None, created_by=None, note='(auto: marked paid)'):
    """Idempotent delete-then-insert, identified by `ref` (not a real SQL
    upsert / no unique constraint relied on) — repeated calls with the same
    ref never double-count. A non-positive amount just clears the marker.
    Reference convention unchanged: 'auto-paid:bill:<id>' / 'auto-paid:ledger:<id>'."""
    auto_payment_remove(session, organization_id, ref)
    if not party_key or amount is None or amount <= 0:
        return None
    payment = Payment(
        organization_id=organization_id,
        party_type=party_type,
        party_key=str(party_key),
        payment_date=when or date.today(),
        amount=float(amount),
        mode=mode,
        reference=ref,
        notes=note,
        source='auto',
        created_by=created_by,
    )
    session.add(payment)
    session.flush()
    return payment


def auto_payment_remove(session, organization_id, ref):
    session.execute(
        text('DELETE FROM payments WHERE organization_id=:org AND reference=:ref'),
        {'org': organization_id, 'ref': ref},
    )


def record_manual_payment(session, organization_id, party_type, party_key, amount,
                           payment_date=None, mode=None, reference=None, notes=None,
                           created_by=None):
    """Validated entry point for a human-recorded payment — mirrors
    payment_add() (app.py:6069-6099) minus the Flask-form/redirect plumbing.
    Raises ValueError on invalid input (party_type/amount) rather than
    flashing+redirecting, since this is a service function, not a route."""
    if party_type not in _PARTY_TYPES:
        raise ValueError(f'party_type must be one of {_PARTY_TYPES}, got {party_type!r}')
    if not party_key:
        raise ValueError('party_key is required')
    if amount is None or amount <= 0:
        raise ValueError('amount must be greater than zero')

    payment = Payment(
        organization_id=organization_id,
        party_type=party_type,
        party_key=str(party_key),
        payment_date=payment_date or date.today(),
        amount=float(amount),
        mode=mode,
        reference=reference,
        notes=notes,
        source='manual',
        created_by=created_by,
        created_at=datetime.now(),
    )
    session.add(payment)
    session.flush()
    return payment
