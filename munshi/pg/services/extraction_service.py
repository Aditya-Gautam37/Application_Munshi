"""Bill/invoice AI-extraction flow — port of app.py's extract_upload(),
_run_extraction_async(), extract_status(), extract_review(). Two tables:
`extractions` (one row per upload batch) and `extracted_invoices` (one row
per file in that batch).

Every function here takes an already-open session and does NOT commit —
the background-thread caller (still a real Python thread, same as SQLite;
Render is a persistent container, no serverless timeout to design around)
opens its own short-lived session per DB touch, exactly mirroring the
SQLite version's own "new get_db() connection per touch, since sqlite3
connections aren't thread-shareable" discipline — Postgres sessions are
also not meant to be shared across threads.
"""
from datetime import datetime

from sqlalchemy import select

from munshi.pg.models import Extraction, ExtractedInvoice


def create_extraction(session, organization_id, mode='combine', status='pending', note=''):
    extraction = Extraction(
        organization_id=organization_id, mode=mode, status=status, note=note,
        created_at=datetime.now(),
    )
    session.add(extraction)
    session.flush()
    return extraction


def get_extraction(session, organization_id, extraction_id):
    return session.execute(
        select(Extraction).where(
            Extraction.id == extraction_id, Extraction.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def update_extraction(session, organization_id, extraction_id, **fields):
    """fields: any of note/status/mode."""
    extraction = get_extraction(session, organization_id, extraction_id)
    if extraction is None:
        return None
    for k in ('note', 'status', 'mode'):
        if k in fields:
            setattr(extraction, k, fields[k])
    session.flush()
    return extraction


def add_extracted_invoice(session, organization_id, extraction_id, file_name, seq,
                           raw_json=None, error=None):
    invoice = ExtractedInvoice(
        organization_id=organization_id, extraction_id=extraction_id,
        file_name=file_name, seq=seq, raw_json=raw_json, error=error,
    )
    session.add(invoice)
    session.flush()
    return invoice


def list_extracted_invoices(session, organization_id, extraction_id):
    return session.execute(
        select(ExtractedInvoice)
        .where(ExtractedInvoice.organization_id == organization_id,
               ExtractedInvoice.extraction_id == extraction_id)
        .order_by(ExtractedInvoice.seq)
    ).scalars().all()


def count_extracted_invoices(session, organization_id, extraction_id):
    return len(list_extracted_invoices(session, organization_id, extraction_id))


def update_extracted_invoice_edited(session, organization_id, invoice_id, edited_json):
    invoice = session.execute(
        select(ExtractedInvoice).where(
            ExtractedInvoice.id == invoice_id, ExtractedInvoice.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if invoice is None:
        return None
    invoice.edited_json = edited_json
    session.flush()
    return invoice
