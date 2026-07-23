"""Small addition needed to unblock ledger entries in PG_MODE: a ledger
entry can reference a diesel vendor by id, and the ledger form's "remember
this vendor by name" autocomplete (app.py's remember_diesel_vendor())
needs a Postgres equivalent. Same shape as transporter_service.py.
"""
from datetime import datetime

from sqlalchemy import func, select

from munshi.pg.models import DieselVendor


def list_diesel_vendors(session):
    return session.scalars(select(DieselVendor).order_by(DieselVendor.name)).all()


def get_or_create_diesel_vendor(session, organization_id, name):
    """Case-insensitive get-or-create by name — mirrors app.py's
    remember_diesel_vendor() (SQLite `COLLATE NOCASE` match). Returns the
    vendor id, or None if name is blank."""
    name = (name or '').strip()
    if not name:
        return None
    existing = session.execute(
        select(DieselVendor).where(
            DieselVendor.organization_id == organization_id,
            func.lower(DieselVendor.name) == name.lower(),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    vendor = DieselVendor(organization_id=organization_id, name=name, created_at=datetime.now())
    session.add(vendor)
    session.flush()
    return vendor.id
