"""Rate-list master (freight_rates) — port of app.py's get_rate_list(),
import_rate_list_from_xlsx()'s DB-write step, and the rate_list_editor()
CRUD routes. Excel-parsing itself (_classify_rate_header, the two-row
header-merge handling, cell coercion) stays in app.py — pure file parsing
with zero DB dependency, nothing to port.

freight_rates has no autoincrement id reuse concerns like the recycle-bin
tables; it's a plain per-org master list keyed by (organization_id,
customer_name, location) — mirrors SQLite's UNIQUE(customer_name, location).
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from munshi.pg.models import FreightRate

_RATE_FIELDS = (
    'party_code', 'dist_twy_km', 'dist_owy_km',
    'lp_owy', 'lp_twy', 'trolla_owy', 'trolla_twy',
)


def list_rates(session, organization_id):
    return session.execute(
        select(FreightRate)
        .where(FreightRate.organization_id == organization_id)
        .order_by(FreightRate.customer_name)
    ).scalars().all()


def get_rate_list(session, organization_id):
    """Shape matches app.py's get_rate_list() — used by new_bill()/edit_bill()
    templates for client-side autofill, not a full row (no id/updated_at)."""
    rows = session.execute(
        select(FreightRate.customer_name, FreightRate.party_code, FreightRate.location,
               FreightRate.dist_twy_km, FreightRate.dist_owy_km, FreightRate.lp_owy,
               FreightRate.lp_twy, FreightRate.trolla_owy, FreightRate.trolla_twy)
        .where(FreightRate.organization_id == organization_id)
        .order_by(FreightRate.customer_name)
    ).all()
    cols = ('customer_name', 'party_code', 'location', 'dist_twy_km', 'dist_owy_km',
            'lp_owy', 'lp_twy', 'trolla_owy', 'trolla_twy')
    return [dict(zip(cols, r)) for r in rows]


def search_rates(session, organization_id, q=None, limit=1000):
    stmt = select(FreightRate).where(FreightRate.organization_id == organization_id)
    if q:
        like = f'%{q}%'
        stmt = stmt.where(
            (FreightRate.customer_name.ilike(like)) |
            (FreightRate.location.ilike(like)) |
            (FreightRate.party_code.ilike(like))
        )
    stmt = stmt.order_by(FreightRate.customer_name).limit(limit)
    return session.execute(stmt).scalars().all()


def get_rate(session, organization_id, rate_id):
    return session.execute(
        select(FreightRate).where(
            FreightRate.id == rate_id, FreightRate.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def create_rate(session, organization_id, customer_name, location, **fields):
    """Raises IntegrityError on a duplicate (customer_name, location) for
    this org — caller catches it and flashes 'already exists', matching
    transporter_service.create_transporter's contract."""
    rate = FreightRate(
        organization_id=organization_id, customer_name=customer_name, location=location,
        updated_at=datetime.now(),
        **{k: v for k, v in fields.items() if k in _RATE_FIELDS},
    )
    session.add(rate)
    session.flush()
    return rate


def update_rate(session, organization_id, rate_id, customer_name, location, **fields):
    rate = get_rate(session, organization_id, rate_id)
    if rate is None:
        return None
    rate.customer_name = customer_name
    rate.location = location
    for k, v in fields.items():
        if k in _RATE_FIELDS:
            setattr(rate, k, v)
    rate.updated_at = datetime.now()
    session.flush()
    return rate


def delete_rate(session, organization_id, rate_id):
    """Returns (customer_name, location) for the deleted row (audit-log
    summary at the call site), or None if it didn't exist in this org."""
    rate = get_rate(session, organization_id, rate_id)
    if rate is None:
        return None
    label = (rate.customer_name, rate.location)
    session.delete(rate)
    session.flush()
    return label


def clear_rates(session, organization_id):
    rates = list_rates(session, organization_id)
    for r in rates:
        session.delete(r)
    session.flush()


def upsert_rate_row(session, organization_id, *, customer_name, party_code, location,
                     dist_twy_km, dist_owy_km, lp_owy, lp_twy, trolla_owy, trolla_twy):
    """One row of import_rate_list_from_xlsx()'s upsert loop — mirrors the
    SQLite INSERT ... ON CONFLICT(customer_name, location) DO UPDATE exactly,
    scoped to this org's unique constraint instead."""
    stmt = pg_insert(FreightRate).values(
        organization_id=organization_id, customer_name=customer_name, party_code=party_code,
        location=location, dist_twy_km=dist_twy_km, dist_owy_km=dist_owy_km,
        lp_owy=lp_owy, lp_twy=lp_twy, trolla_owy=trolla_owy, trolla_twy=trolla_twy,
        updated_at=datetime.now(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=['organization_id', 'customer_name', 'location'],
        set_={
            'party_code': stmt.excluded.party_code,
            'dist_twy_km': stmt.excluded.dist_twy_km,
            'dist_owy_km': stmt.excluded.dist_owy_km,
            'lp_owy': stmt.excluded.lp_owy,
            'lp_twy': stmt.excluded.lp_twy,
            'trolla_owy': stmt.excluded.trolla_owy,
            'trolla_twy': stmt.excluded.trolla_twy,
            'updated_at': stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)
