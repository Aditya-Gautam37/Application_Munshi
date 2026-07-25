"""Vehicle autocomplete-memory master — same shape as driver_service.py.
Port of app.py's remember_vehicle()/get_vehicles().
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from munshi.pg.models import Vehicle


def list_vehicles(session, organization_id):
    return session.execute(
        select(Vehicle)
        .where(Vehicle.organization_id == organization_id)
        .order_by(Vehicle.updated_at.desc())
    ).scalars().all()


def remember_vehicle(session, organization_id, vehicle_no):
    """Mirrors remember_vehicle()'s SQLite ON CONFLICT(vehicle_no) DO UPDATE,
    scoped to (organization_id, vehicle_no). No-op if blank."""
    if not vehicle_no:
        return
    now = datetime.now()
    stmt = pg_insert(Vehicle).values(
        organization_id=organization_id, vehicle_no=vehicle_no.strip().upper(), updated_at=now,
    ).on_conflict_do_update(
        index_elements=['organization_id', 'vehicle_no'],
        set_={'updated_at': now},
    )
    session.execute(stmt)
    session.flush()
