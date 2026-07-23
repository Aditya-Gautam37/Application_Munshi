"""Postgres-backed user/auth data access. Mirrors
munshi/repositories/user_repository.py's exact exported surface — that
repository delegates here when PG_MODE is on, so neither
munshi/services/auth_service.py nor munshi/api/auth.py (the actual
/login, /setup, /users* routes) need to change at all.

Also ports the three login-lockout functions inlined in
munshi/services/auth_service.py against raw SQLite (login_lockout_remaining,
record_login_failure, clear_login_failures) — these target the EXISTING
org-scoped `login_failures` table (munshi.pg.models.LoginFailure) rather
than a new table, tagged with this single-business deployment's one fixed
organization id. See munshi/pg/auth_models.py's module docstring for why.

Every function here is self-committing (uses the shared pg session, commits
before returning), matching user_repository.py's existing self-committing
style — callers don't need to know a Postgres session exists at all.
"""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from munshi.pg import database as pg_database
from munshi.pg.auth_models import User
from munshi.pg.models import LoginFailure

_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_LOCKOUT_SECONDS = 15 * 60


def _org_id():
    org_id = os.environ.get('MUNSHI_ORGANIZATION_ID', '').strip()
    if not org_id:
        raise RuntimeError('MUNSHI_ORGANIZATION_ID is not set — required whenever PG_MODE is on.')
    return org_id


# ── users ─────────────────────────────────────────────────────────────────

def get_by_username(username):
    session = pg_database.get_session()
    return session.execute(select(User).where(User.username == username)).scalar_one_or_none()


def get_active_by_username(username):
    session = pg_database.get_session()
    return session.execute(
        select(User).where(User.username == username, User.is_active.is_(True))
    ).scalar_one_or_none()


def exists(username):
    return get_by_username(username) is not None


def list_all():
    session = pg_database.get_session()
    return session.execute(select(User).order_by(User.role.desc(), User.username)).scalars().all()


def create(username, password_hash, full_name, role, must_change_password):
    session = pg_database.get_session()
    session.add(User(
        username=username,
        password_hash=password_hash,
        full_name=full_name,
        role=role,
        is_active=True,
        must_change_password=bool(must_change_password),
        created_at=datetime.now().isoformat(),
    ))
    session.commit()


def update_password(username, password_hash, must_change_password):
    session = pg_database.get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        return False
    user.password_hash = password_hash
    user.must_change_password = bool(must_change_password)
    session.commit()
    return True


def update_last_login(username):
    session = pg_database.get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is not None:
        user.last_login = datetime.now().isoformat()
        session.commit()


def set_active(username, is_active):
    session = pg_database.get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is not None:
        user.is_active = bool(is_active)
        session.commit()


def set_role(username, role):
    session = pg_database.get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is not None:
        user.role = role
        session.commit()


# ── login lockout (reuses the existing multi-tenant login_failures table) ──

def login_lockout_remaining(username):
    """Port of munshi/services/auth_service.py's SQLite version — same
    window/threshold constants, same prune-stale-then-check-count logic,
    targeting LoginFailure.identifier instead of a SQLite username column.
    Always uses timezone-aware datetimes: `failed_at` is a real `timestamptz`
    column here (unlike SQLite's ISO-text), and comparing an aware value
    against a naive one raises at runtime — not just a style nit."""
    if not username:
        return 0
    session = pg_database.get_session()
    org_id = _org_id()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=_LOGIN_WINDOW_SECONDS)

    session.execute(
        delete(LoginFailure).where(
            LoginFailure.organization_id == org_id,
            LoginFailure.identifier == username,
            LoginFailure.failed_at < cutoff,
        )
    )
    session.commit()

    rows = session.execute(
        select(LoginFailure.failed_at)
        .where(LoginFailure.organization_id == org_id, LoginFailure.identifier == username)
        .order_by(LoginFailure.failed_at)
    ).scalars().all()

    if len(rows) < _LOGIN_MAX_FAILURES:
        return 0
    last_failed = rows[-1]
    if last_failed.tzinfo is None:  # defensive, in case the driver ever returns naive
        last_failed = last_failed.replace(tzinfo=timezone.utc)
    locked_until = last_failed + timedelta(seconds=_LOGIN_LOCKOUT_SECONDS)
    return max(0, int((locked_until - now).total_seconds()))


def record_login_failure(username):
    if not username:
        return
    session = pg_database.get_session()
    session.add(LoginFailure(
        organization_id=_org_id(), identifier=username, failed_at=datetime.now(timezone.utc),
    ))
    session.commit()


def clear_login_failures(username):
    if not username:
        return
    session = pg_database.get_session()
    session.execute(
        delete(LoginFailure).where(
            LoginFailure.organization_id == _org_id(), LoginFailure.identifier == username,
        )
    )
    session.commit()
