"""Postgres-backed settings KV store — reuses the EXISTING `Setting` model
(munshi/pg/models.py, composite PK organization_id+key, already migrated in
0001_baseline.py) rather than a second, org-less table, scoped to this
single-business deployment's one fixed organization id.

Self-committing, matching app.py's get_setting(key)/set_setting(key, value)
call convention exactly (no session/conn argument at the call site) — so
app.py's own get_setting/set_setting only need a thin `if PG_MODE:` branch,
not a rewrite of every caller across the file.
"""
from sqlalchemy import select

from munshi.pg import database as pg_database
from munshi.pg.models import Setting


def get_setting(organization_id, key):
    session = pg_database.get_session()
    value = session.execute(
        select(Setting.value).where(Setting.organization_id == organization_id, Setting.key == key)
    ).scalar_one_or_none()
    return value if value is not None else ''


def get_all_settings(organization_id):
    """All settings for this org in a single round trip — used by app.py's
    get_setting() to build a per-request cache (see its own docstring for
    why: individual get_setting() calls add up to dozens per page render,
    each a separate network round trip to Postgres)."""
    session = pg_database.get_session()
    rows = session.execute(
        select(Setting.key, Setting.value).where(Setting.organization_id == organization_id)
    ).all()
    return {k: v for k, v in rows}


def set_setting(organization_id, key, value):
    session = pg_database.get_session()
    row = session.execute(
        select(Setting).where(Setting.organization_id == organization_id, Setting.key == key)
    ).scalar_one_or_none()
    if row is None:
        session.add(Setting(organization_id=organization_id, key=key, value=value))
    else:
        row.value = value
    session.commit()
