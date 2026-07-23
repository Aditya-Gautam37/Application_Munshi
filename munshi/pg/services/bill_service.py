"""GST invoice creation — port of new_bill()'s business logic (app.py
~2461-2564), minus Flask form/request/redirect plumbing. Legal document math
lives in munshi.utils.gst.compute_gst_split(), imported verbatim/unchanged —
it's already a pure function with zero DB dependency, so it is NOT
re-implemented here, only called.

Not ported in this phase (flagged, not silently dropped):
  - AuditLog write (new_bill() always logs; no audit-write helper exists yet
    under munshi/pg/services/ — deferred to a later phase).
  - remember_recipient()/remember_vehicle() autocomplete-memory side effects
    (no recipient_service/vehicle_service exists yet — deferred).
"""
from datetime import datetime

from sqlalchemy import select

from munshi.pg.models import Bill, LedgerEntry
from munshi.pg.services.numbering_service import allocate_number
from munshi.utils.gst import compute_gst_split


def _parse_amount(v):
    """Copy of app.py:2730's _parse_amount — not imported from app.py to
    keep munshi/pg/ fully decoupled from the Flask/SQLite app (importing
    app.py would execute its whole module-level setup, including Flask app
    creation). Tolerantly coerces a hand-typed money value to a float, never
    raises: accepts Indian-style commas, a Rs/INR prefix, stray spaces;
    blank or unparseable input becomes 0.0."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    for junk in (',', '₹', 'Rs.', 'Rs', 'INR', ' '):
        s = s.replace(junk, '')
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def create_bill(session, organization_id, *, deliveries, bill_date, recipient_name,
                 recipient_address=None, recipient_gstin=None, state_code=None,
                 trip_type=None, vehicle_no=None, freight_type=None, delivery_month=None,
                 client_name=None, hsn_sac='996511', place_of_supply='', reverse_charge=False,
                 gst_pct=0, supplier_state='09', from_ledger_id=None):
    """`deliveries` is a list of per-delivery dicts (JSON-serializable, stored
    directly into the JSONB column — no json.dumps() needed, unlike SQLite);
    each dict's 'value_of_supply' key is summed for taxable_value, same as
    new_bill()'s `sum(_parse_amount(d['value_of_supply']) for d in deliveries)`.

    Delivery-count (1..20) and gst_pct (0..28) clamps are kept here as
    business rules (a bill legally can't have 0 or >20 deliveries, GST% can't
    exceed 28), not form-parsing — so a future caller other than a route gets
    the same guardrails a human filling the form does.

    Caller commits."""
    if not (1 <= len(deliveries) <= 20):
        raise ValueError(f'a bill must have 1-20 deliveries, got {len(deliveries)}')

    taxable_value = sum(_parse_amount(d.get('value_of_supply')) for d in deliveries)

    gst_pct = max(0, min(28, float(gst_pct or 0))) if not reverse_charge else 0
    tax = compute_gst_split(taxable_value, gst_pct, supplier_state, place_of_supply, reverse_charge)

    n = allocate_number(session, organization_id, 'bill_no')
    bill_no = f'JL-{n:04d}'

    bill = Bill(
        organization_id=organization_id,
        bill_no=bill_no,
        bill_date=bill_date,
        recipient_name=recipient_name,
        recipient_address=recipient_address,
        recipient_gstin=recipient_gstin,
        state_code=state_code,
        trip_type=trip_type,
        vehicle_no=vehicle_no,
        freight_type=freight_type,
        delivery_month=delivery_month,
        client_name=client_name,
        total_amount=tax['grand_total'],
        deliveries=deliveries,
        created_at=datetime.now(),
        hsn_sac=hsn_sac,
        taxable_value=taxable_value,
        reverse_charge=reverse_charge,
        place_of_supply=place_of_supply,
        igst_pct=tax['igst_pct'],
        cgst_pct=tax['cgst_pct'],
        sgst_pct=tax['sgst_pct'],
        igst_amount=tax['igst_amount'],
        cgst_amount=tax['cgst_amount'],
        sgst_amount=tax['sgst_amount'],
    )
    session.add(bill)
    session.flush()  # populate bill.id

    if from_ledger_id is not None:
        bill.ledger_entry_id = from_ledger_id
        ledger_entry = session.execute(
            select(LedgerEntry).where(
                LedgerEntry.id == from_ledger_id,
                LedgerEntry.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if ledger_entry is not None:
            ledger_entry.bill_id = bill.id
            ledger_entry.updated_at = datetime.now()

    return bill
