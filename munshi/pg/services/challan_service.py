"""Challans — port of app.py's challan routes (challans_index,
challan_new_manual, challan_extract_upload, challan_review). Delete
(→ recycle bin) is NOT here yet — that's a separate phase, alongside the
matching bill/ledger/payment delete gaps (see .claude/plans/
streamed-giggling-crescent.md).

LR-number allocation uses numbering_service.allocate_number() (the same
race-free SELECT...FOR UPDATE mechanism already proven for bill numbers)
rather than porting SQLite's find_unique_lr_no() scan-and-collision-check
loop. Deliberate simplification, same precedent as bill numbering: a
caller-preferred/AI-extracted LR number is no longer tried first — every
challan gets the next sequential number for its org. Flagged here since
it's a real, intentional behavior change, not an oversight.
"""
from datetime import datetime

from sqlalchemy import select

from munshi.pg.models import Challan, LedgerEntry
from munshi.pg.services.ledger_service import create_ledger_entry
from munshi.pg.services.numbering_service import allocate_number

_CHALLAN_FIELDS = (
    'lr_no', 'challan_date', 'consignor_name', 'consignor_address',
    'consignee_name', 'consignee_address', 'from_city_state', 'to_city_state',
    'invoice_no', 'invoice_date', 'consignment_value', 'gst_number',
    'no_of_articles', 'description', 'value_of_goods', 'weight_kg',
    'del_no', 'shipment_no', 'cost_no', 'seal_no',
    'driver_name', 'driver_mobile', 'truck_no',
    'gate_in_time', 'gate_out_time', 'lane_transit_time', 'expected_arrival',
    'source_image', 'raw_extraction', 'invoice_source_image', 'invoice_raw_extraction',
    'confidence_json', 'status', 'notes', 'pod_doc_no',
)


def allocate_lr_no(session, organization_id):
    return str(allocate_number(session, organization_id, 'lr_no'))


def list_challans(session, organization_id, limit=200):
    return session.execute(
        select(Challan)
        .where(Challan.organization_id == organization_id)
        .order_by(Challan.id.desc())
        .limit(limit)
    ).scalars().all()


def get_challan(session, organization_id, challan_id):
    return session.execute(
        select(Challan).where(
            Challan.id == challan_id, Challan.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def create_draft(session, organization_id):
    """Blank challan, no photo/AI step — mirrors challan_new_manual()."""
    lr_no = allocate_lr_no(session, organization_id)
    challan = Challan(
        organization_id=organization_id, lr_no=lr_no, status='draft',
        created_at=datetime.now(),
    )
    session.add(challan)
    session.flush()
    return challan


def create_from_extraction(session, organization_id, **fields):
    """Mirrors challan_extract_upload()'s INSERT — fields already extracted
    from AI results by the caller. Always allocates a fresh LR number (see
    module docstring on why the AI-extracted candidate isn't tried first)."""
    lr_no = allocate_lr_no(session, organization_id)
    challan = Challan(
        organization_id=organization_id,
        status='draft',
        created_at=datetime.now(),
        lr_no=lr_no,
        **{k: v for k, v in fields.items() if k in _CHALLAN_FIELDS and k != 'lr_no'},
    )
    session.add(challan)
    session.flush()
    return challan


def update_challan(session, organization_id, challan_id, created_by=None, **fields):
    """Mirrors challan_review()'s POST branch: updates the row, sets
    status='open', and — the first time a challan leaves 'draft' — auto-
    creates a linked ledger_entries draft (same trigger condition as
    SQLite: status was 'draft' AND no ledger_entry_id yet). Returns
    (challan, new_ledger_entry_or_None). Caller commits."""
    challan = get_challan(session, organization_id, challan_id)
    if challan is None:
        return None, None

    was_draft = challan.status == 'draft'
    had_ledger_entry = challan.ledger_entry_id is not None

    for k, v in fields.items():
        if k in _CHALLAN_FIELDS:
            setattr(challan, k, v)
    challan.status = 'open'
    challan.updated_at = datetime.now()

    new_entry = None
    if was_draft and not had_ledger_entry:
        weight_kg = fields.get('weight_kg')
        new_entry = create_ledger_entry(
            session, organization_id,
            challan_id=challan.id,
            entry_date=fields.get('challan_date'),
            gr_no=fields.get('lr_no'),
            vehicle_no=fields.get('truck_no'),
            station=fields.get('to_city_state'),
            shipment_no=fields.get('invoice_no'),
            trip_type='One Way',
            mt_qty=(weight_kg / 1000.0) if weight_kg else None,
            freight=0, advance_cash=0, advance_account=0, diesel=0,
            remarks=f'Auto-created from challan LR-{fields.get("lr_no")} · {fields.get("consignee_name") or ""}',
        )
        challan.ledger_entry_id = new_entry.id

    session.flush()
    return challan, new_entry
