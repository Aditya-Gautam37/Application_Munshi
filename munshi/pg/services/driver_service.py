"""Driver master — same shape as transporter_service.py/diesel_vendor_service.py.
Port of app.py's remember_driver()/get_drivers().
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from munshi.pg.models import Driver


def list_drivers(session, organization_id):
    return session.execute(
        select(Driver)
        .where(Driver.organization_id == organization_id)
        .order_by(Driver.updated_at.desc())
    ).scalars().all()


def get_or_create_driver(session, organization_id, name, mobile):
    """Get-or-create-or-update by (organization_id, mobile) — mirrors
    remember_driver()'s SQLite `ON CONFLICT(mobile) DO UPDATE`, but the
    conflict target here is the tenant-scoped UniqueConstraint
    (organization_id, mobile), not a bare mobile PK. Digits-only mobile,
    minimum 8 digits, same validation as the SQLite original. Returns None
    if mobile is blank/too short (no-op, matches original silently
    skipping)."""
    mobile = ''.join(c for c in str(mobile or '') if c.isdigit())
    if len(mobile) < 8:
        return None
    now = datetime.now()
    stmt = pg_insert(Driver).values(
        organization_id=organization_id, mobile=mobile, name=(name or '').strip(), updated_at=now,
    ).on_conflict_do_update(
        index_elements=['organization_id', 'mobile'],
        set_={'name': (name or '').strip(), 'updated_at': now},
    ).returning(Driver.mobile)
    session.execute(stmt)
    session.flush()
    return mobile
