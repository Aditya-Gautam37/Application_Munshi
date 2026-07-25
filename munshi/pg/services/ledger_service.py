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
    'challan_id', 'entry_date', 'gr_no', 'vehicle_no', 'station', 'shipment_no', 'trip_type',
    'mt_qty', 'freight', 'advance_cash', 'advance_account', 'diesel',
    'diesel_vendor_id', 'transporter_id', 'remarks',
)

POD_ADJUSTMENT_FIELDS = ('shortage', 'leakage', 'breakage', 'unloading',
                         'detention', 'toll_tax', 'excess_km')
_POD_FIELDS = ('pod_received', 'pod_date', 'pod_image', 'delivery_date') + POD_ADJUSTMENT_FIELDS
_AMOUNT_FIELDS = ('freight', 'advance_cash', 'advance_account', 'diesel')


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


def find_duplicate_gr(session, organization_id, gr_no, exclude_id=None):
    """Mirrors app.py's _find_duplicate_gr() — heads-up only, deliberately
    not a unique constraint (some businesses legitimately reuse GR books)."""
    gr_no = (gr_no or '').strip()
    if not gr_no:
        return []
    stmt = select(LedgerEntry.id, LedgerEntry.entry_date, LedgerEntry.vehicle_no, LedgerEntry.freight).where(
        LedgerEntry.organization_id == organization_id, LedgerEntry.gr_no == gr_no,
    )
    if exclude_id:
        stmt = stmt.where(LedgerEntry.id != exclude_id)
    rows = session.execute(stmt).all()
    return [{'id': r.id, 'entry_date': r.entry_date, 'vehicle_no': r.vehicle_no, 'freight': r.freight} for r in rows]


def update_pod(session, organization_id, le_id, **fields):
    """Mirrors ledger_pod()'s UPDATE — `fields` may include any of
    _POD_FIELDS. Returns the entry (post-update) and a dict of its
    pre-update values for _POD_FIELDS/transporter_id/paid* (used by the
    caller for the audit diff and the payments-mirror sync). Caller commits."""
    entry = get_ledger_entry(session, organization_id, le_id)
    if entry is None:
        return None, None
    before = {k: getattr(entry, k, None) for k in
              _POD_FIELDS + ('transporter_id', 'paid', 'paid_amount', 'paid_date', 'paid_mode', 'gr_no')}
    for k, v in fields.items():
        if k in _POD_FIELDS:
            setattr(entry, k, v)
    entry.updated_at = datetime.now()
    session.flush()
    return entry, before


def update_amounts(session, organization_id, le_id, **fields):
    """Mirrors ledger_amounts()'s UPDATE — `fields` may include any of
    _AMOUNT_FIELDS. Returns (entry, before_dict) like update_pod(). Caller
    commits."""
    entry = get_ledger_entry(session, organization_id, le_id)
    if entry is None:
        return None, None
    before = {k: getattr(entry, k, None) for k in
              _AMOUNT_FIELDS + ('transporter_id', 'paid', 'paid_amount', 'paid_date', 'paid_mode', 'gr_no')}
    for k, v in fields.items():
        if k in _AMOUNT_FIELDS:
            setattr(entry, k, v)
    entry.updated_at = datetime.now()
    session.flush()
    return entry, before


def bulk_mark_pod(session, organization_id, ids, pod_date):
    """Mirrors ledger_bulk_pod() — only flips rows not already POD-received;
    a per-row COALESCE(pod_date, ...) so an existing date is never
    overwritten. Returns the number of rows affected. Caller commits."""
    rows = session.execute(
        select(LedgerEntry).where(
            LedgerEntry.organization_id == organization_id,
            LedgerEntry.id.in_(ids),
            LedgerEntry.pod_received.is_(False),
        )
    ).scalars().all()
    for entry in rows:
        entry.pod_received = True
        entry.pod_date = entry.pod_date or pod_date
        entry.updated_at = datetime.now()
    session.flush()
    return len(rows)


def bulk_mark_paid(session, organization_id, ids, paid_date, mode):
    """Mirrors ledger_bulk_paid() — only flips rows not already paid; returns
    the list of newly-paid entries (caller writes one payments row per
    entry via payment_service.auto_payment_upsert, same as the single-entry
    ledger_paid() flow). Caller commits."""
    rows = session.execute(
        select(LedgerEntry).where(
            LedgerEntry.organization_id == organization_id,
            LedgerEntry.id.in_(ids),
            LedgerEntry.paid.is_(False),
        )
    ).scalars().all()
    for entry in rows:
        entry.paid = True
        entry.paid_date = entry.paid_date or paid_date
        entry.paid_mode = entry.paid_mode or mode
        entry.updated_at = datetime.now()
    session.flush()
    return rows


def duplicate_entry(session, organization_id, le_id, entry_date):
    """Mirrors ledger_duplicate() — clones freight/advance/diesel/vehicle/
    station/transporter, resets GR No./POD/paid state. Returns the new
    entry, or None if le_id doesn't resolve within this org. Caller
    commits."""
    src = get_ledger_entry(session, organization_id, le_id)
    if src is None:
        return None
    new_entry = LedgerEntry(
        organization_id=organization_id, entry_date=entry_date, gr_no='',
        vehicle_no=src.vehicle_no, station=src.station, shipment_no=src.shipment_no,
        trip_type=src.trip_type or 'One Way', mt_qty=src.mt_qty, freight=src.freight,
        advance_cash=src.advance_cash or 0, advance_account=src.advance_account or 0,
        diesel=src.diesel or 0, diesel_vendor_id=src.diesel_vendor_id,
        transporter_id=src.transporter_id, weight_kg=src.weight_kg,
        remarks=f'Duplicated from GR-{src.gr_no or src.id}', created_at=datetime.now(),
    )
    session.add(new_entry)
    session.flush()
    return new_entry
