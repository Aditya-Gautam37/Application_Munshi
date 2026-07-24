"""Ledger-page AI extraction — port of app.py's ledger_extract_upload()/
ledger_extract_review(). Single-table flow (ledger_extractions), unlike
the bill/invoice extraction pair (extractions + extracted_invoices).
"""
from datetime import datetime

from sqlalchemy import select

from munshi.pg.models import LedgerExtraction


def create_ledger_extraction(session, organization_id, source_image, page_date, raw_json, status='pending'):
    extraction = LedgerExtraction(
        organization_id=organization_id, source_image=source_image, page_date=page_date,
        raw_json=raw_json, status=status, created_at=datetime.now(),
    )
    session.add(extraction)
    session.flush()
    return extraction


def get_ledger_extraction(session, organization_id, le_id):
    return session.execute(
        select(LedgerExtraction).where(
            LedgerExtraction.id == le_id, LedgerExtraction.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def update_ledger_extraction(session, organization_id, le_id, **fields):
    """fields: any of status/edited_json."""
    extraction = get_ledger_extraction(session, organization_id, le_id)
    if extraction is None:
        return None
    for k in ('status', 'edited_json'):
        if k in fields:
            setattr(extraction, k, fields[k])
    session.flush()
    return extraction
