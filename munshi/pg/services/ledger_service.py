"""Ledger POD/paid-flag balance logic — port of _ledger_balance() (app.py
~4821-4832) and ledger_paid() (app.py ~5209-5254).

mark_ledger_paid() preserves two SQLite quirks verbatim, per the "faithful
port, not a redesign" decision:
  - `paid_amount` of 0/blank falls back to the full computed net balance, not
    zero. This is a known, pre-existing behavior (arguably a latent bug — a
    legitimate "settled for zero, e.g. written off" entry can't be recorded
    via this path) — NOT fixed here; see
    test_mark_ledger_paid_falsy_amount_falls_back_to_net, which documents it
    as intentional-quirk-preserved rather than an oversight.
  - the auto-payment mirror only fires `if transporter_id` — a trip with no
    assigned transporter has no AP party to record a payment against, so
    it's silently skipped, not an error.
"""
from datetime import datetime

from sqlalchemy import select

from munshi.pg.models import LedgerEntry
from munshi.pg.services.payment_service import auto_payment_remove, auto_payment_upsert

_ENTRY_FIELDS = (
    'entry_date', 'gr_no', 'vehicle_no', 'station', 'shipment_no', 'trip_type',
    'mt_qty', 'freight', 'advance_cash', 'advance_account', 'diesel',
    'diesel_vendor_id', 'transporter_id', 'remarks',
)


def ledger_balance(entry):
    """Net amount owed to the transporter for one trip. Takes a LedgerEntry
    ORM instance (or any object with these attributes via getattr) rather
    than a dict/Row — pure function, no DB access."""
    g = lambda k: float(getattr(entry, k, None) or 0)
    return (g('freight') - g('advance_cash') - g('advance_account') - g('diesel')
            - g('shortage') - g('leakage') - g('breakage') - g('unloading')
            + g('detention') + g('toll_tax') + g('excess_km'))


def get_ledger_entry(session, organization_id, le_id):
    return session.execute(
        select(LedgerEntry).where(
            LedgerEntry.id == le_id,
            LedgerEntry.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def list_ledger_entries(session, organization_id):
    return session.execute(
        select(LedgerEntry)
        .where(LedgerEntry.organization_id == organization_id)
        .order_by(LedgerEntry.entry_date.desc(), LedgerEntry.id.desc())
        .limit(500)
    ).scalars().all()


def create_ledger_entry(session, organization_id, **fields):
    """`fields` may include any of _ENTRY_FIELDS. Caller commits. Mirrors
    _ledger_save_new() (app.py ~5025-5056) minus Flask-form plumbing and the
    duplicate-GR heads-up flash (still computed at the app.py call site via
    a plain SELECT — that's display-only, not money-critical)."""
    entry = LedgerEntry(
        organization_id=organization_id,
        created_at=datetime.now(),
        **{k: v for k, v in fields.items() if k in _ENTRY_FIELDS},
    )
    session.add(entry)
    session.flush()
    return entry


def update_ledger_entry(session, organization_id, le_id, **fields):
    """Mirrors ledger_view()'s POST branch (app.py ~5062-5111) minus
    Flask-form/audit-diff plumbing. Returns the updated entry, or None if
    le_id doesn't resolve within this org."""
    entry = get_ledger_entry(session, organization_id, le_id)
    if entry is None:
        return None
    for k, v in fields.items():
        if k in _ENTRY_FIELDS:
            setattr(entry, k, v)
    entry.updated_at = datetime.now()
    session.flush()
    return entry


def mark_ledger_paid(session, organization_id, le_id, *, is_paid, paid_date=None,
                      paid_mode=None, paid_amount=None, paid_reference=None,
                      created_by=None):
    """Caller commits. Raises ValueError if le_id doesn't resolve within this org."""
    entry = get_ledger_entry(session, organization_id, le_id)
    if entry is None:
        raise ValueError(f'ledger entry {le_id} not found in this organization')

    ref = f'auto-paid:ledger:{le_id}'

    if is_paid:
        net = ledger_balance(entry)  # computed BEFORE the paid-flag mutation below
        entry.paid = True
        entry.paid_date = paid_date or datetime.now().date()
        entry.paid_mode = paid_mode
        entry.paid_amount = paid_amount
        entry.paid_reference = paid_reference
        entry.updated_at = datetime.now()

        amt = paid_amount or net  # preserved quirk: falsy paid_amount falls back to net
        if entry.transporter_id:
            auto_payment_upsert(
                session, organization_id, 'transporter', entry.transporter_id, amt, ref,
                when=paid_date, mode=paid_mode, created_by=created_by,
            )
    else:
        entry.paid = False
        entry.paid_date = None
        entry.paid_mode = None
        entry.paid_amount = None
        entry.paid_reference = None
        entry.updated_at = datetime.now()
        auto_payment_remove(session, organization_id, ref)

    session.flush()
    return entry
