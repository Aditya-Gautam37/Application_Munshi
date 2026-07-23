"""Deliberately the most boring tenant table available (no JSONB, no money
columns — zero overlap with the GST/balance regression surface). Its only
job in Phase 1 is proving the session/RLS pattern holds for a second table,
not just the org/membership bootstrap tables.

Every function here assumes the caller already called
munshi.pg.database.set_tenant_context() on `session` — this module doesn't
set it itself, matching the intended production shape (set once per request,
before any query, from validated JWT claims)."""
from datetime import datetime

from sqlalchemy import select

from munshi.pg.models import Transporter


def list_transporters(session):
    return session.scalars(select(Transporter).order_by(Transporter.name)).all()


def create_transporter(session, organization_id, name, mobile=None, bank_details=None, notes=None):
    transporter = Transporter(
        organization_id=organization_id, name=name, mobile=mobile,
        bank_details=bank_details, notes=notes, created_at=datetime.now(),
    )
    session.add(transporter)
    session.flush()
    return transporter


def get_transporter(session, organization_id, transporter_id):
    return session.execute(
        select(Transporter).where(
            Transporter.id == transporter_id, Transporter.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def delete_transporter(session, organization_id, transporter_id):
    """Returns the deleted transporter's name (for an audit-log summary at
    the call site), or None if it didn't exist in this org."""
    transporter = get_transporter(session, organization_id, transporter_id)
    if transporter is None:
        return None
    name = transporter.name
    session.delete(transporter)
    session.flush()
    return name
