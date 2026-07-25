"""Recipient (client) autocomplete-memory master — same shape as
driver_service.py. Port of app.py's remember_recipient()/get_recipients().
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from munshi.pg.models import Recipient


def list_recipients(session, organization_id):
    return session.execute(
        select(Recipient)
        .where(Recipient.organization_id == organization_id)
        .order_by(Recipient.updated_at.desc())
    ).scalars().all()


def remember_recipient(session, organization_id, name, address, gstin, state_code, freight_rate=None):
    """Mirrors remember_recipient()'s SQLite ON CONFLICT(name) DO UPDATE,
    scoped to (organization_id, name). Only touches freight_rate if a
    non-empty value was provided (same as the original — a blank Freight
    Rate field on the bill form doesn't erase a previously-remembered rate).
    No-op if name is blank."""
    if not name:
        return
    rate_val = None
    if freight_rate not in (None, '', 0, '0'):
        try:
            rate_val = float(freight_rate)
        except (TypeError, ValueError):
            rate_val = None
    if rate_val is None:
        return
    now = datetime.now()
    stmt = pg_insert(Recipient).values(
        organization_id=organization_id, name=name.strip(), address=address or '',
        gstin=gstin or '', state_code=state_code or '', freight_rate=rate_val, updated_at=now,
    ).on_conflict_do_update(
        index_elements=['organization_id', 'name'],
        set_={'address': address or '', 'gstin': gstin or '', 'state_code': state_code or '',
              'freight_rate': rate_val, 'updated_at': now},
    )
    session.execute(stmt)
    session.flush()
