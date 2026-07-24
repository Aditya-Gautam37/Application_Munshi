"""Postgres-backed audit log. Fixes a real, confirmed gap: app.py's
log_audit(conn, ...) always writes to SQLite unconditionally, even from
routes already running in PG_MODE — and for transporter_add/
transporter_delete specifically, their PG_MODE branch doesn't call
log_audit at all, so those two actions currently log nothing whatsoever,
not even to SQLite. Call this ALONGSIDE (not instead of) the existing
SQLite log_audit at already-migrated call sites, so nothing regresses for
routes not yet touched by this phase.
"""
from sqlalchemy import cast, desc, or_, select
from sqlalchemy.types import Text as SaText

from munshi.pg.models import AuditLog


def log_audit(session, organization_id, action, entity, entity_id, summary='', changes=None, user=None):
    """Caller commits (matches the SQLite log_audit's contract exactly —
    'commit handled by caller')."""
    entry = AuditLog(
        organization_id=organization_id,
        user_name=user,
        action=action,
        entity=entity,
        entity_id=entity_id,
        summary=(summary or '')[:500],
        changes=changes,
    )
    session.add(entry)
    session.flush()
    return entry


def get_audit_for(session, organization_id, entity, entity_id, limit=50):
    return session.execute(
        select(AuditLog)
        .where(
            AuditLog.organization_id == organization_id,
            AuditLog.entity == entity,
            AuditLog.entity_id == entity_id,
        )
        .order_by(desc(AuditLog.occurred_at))
        .limit(limit)
    ).scalars().all()


def list_audit_log(session, organization_id, *, user=None, action=None, entity=None,
                    date_from=None, date_to=None, q=None, limit=500):
    """Mirrors audit_log_view()'s filter logic (app.py) — exact-match on
    user/action/entity, occurred_at range, `q` as a substring search over
    both summary and changes (changes is JSONB here, cast to text for the
    search — SQLite's version searches the same column as a JSON string)."""
    stmt = select(AuditLog).where(AuditLog.organization_id == organization_id)
    if user:
        stmt = stmt.where(AuditLog.user_name == user)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if date_from:
        stmt = stmt.where(AuditLog.occurred_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.occurred_at <= date_to)
    if q:
        like = f'%{q}%'
        stmt = stmt.where(or_(
            AuditLog.summary.ilike(like),
            cast(AuditLog.changes, SaText).ilike(like),
        ))
    stmt = stmt.order_by(desc(AuditLog.occurred_at)).limit(limit)
    return session.execute(stmt).scalars().all()


def distinct_values(session, organization_id, column_name):
    """column_name is one of 'user_name'/'action'/'entity' — powers the
    /audit filter dropdowns, mirroring audit_log_view()'s three
    `SELECT DISTINCT ...` calls."""
    column = getattr(AuditLog, column_name)
    rows = session.execute(
        select(column)
        .where(AuditLog.organization_id == organization_id, column.is_not(None))
        .distinct()
        .order_by(column)
    ).scalars().all()
    return [r for r in rows if r]
