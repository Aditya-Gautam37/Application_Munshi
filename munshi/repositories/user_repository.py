"""Data access for the `users` table — replaces the inline
`conn.execute('... FROM users ...')` calls that used to live in app.py's
auth/setup/users routes, with the same queries expressed against
models.User via SQLAlchemy.

PG_MODE (on whenever DATABASE_URL is set — the single-business Postgres
cutover) delegates every function here to munshi/pg/services/user_service.py
instead of the SQLite engine below. Deferred import inside each branch: the
desktop PyInstaller build excludes psycopg/alembic/jwt entirely
(build/munshi.spec), so munshi.pg must never be imported at module top
level here, only inside the PG_MODE branch that's unreachable when it's
unset. This is the ONLY place the switch lives for the whole auth domain —
munshi/services/auth_service.py and munshi/api/auth.py (the actual /login,
/setup, /users* routes) call only this repository and need no changes.
"""
import os
from datetime import datetime

from sqlalchemy import select

from munshi.database.engine import get_session
from munshi.models import User

PG_MODE = bool(os.environ.get('DATABASE_URL', '').strip())


def get_by_username(username):
    """Return the User row (any status), or None."""
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.get_by_username(username)
    session = get_session()
    return session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()


def get_active_by_username(username):
    """Return the User row only if is_active=1 — mirrors the old
       `WHERE username=? AND is_active=1` in login()."""
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.get_active_by_username(username)
    session = get_session()
    return session.execute(
        select(User).where(User.username == username, User.is_active == 1)
    ).scalar_one_or_none()


def exists(username):
    return get_by_username(username) is not None


def list_all():
    """All users, ordered role DESC then username — mirrors users_index()'s
       `ORDER BY role DESC, username`."""
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.list_all()
    session = get_session()
    return session.execute(
        select(User).order_by(User.role.desc(), User.username)
    ).scalars().all()


def create(username, password_hash, full_name, role, must_change_password):
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.create(username, password_hash, full_name, role, must_change_password)
    session = get_session()
    session.add(User(
        username=username,
        password_hash=password_hash,
        full_name=full_name,
        role=role,
        is_active=1,
        must_change_password=1 if must_change_password else 0,
        created_at=datetime.now().isoformat(),
    ))
    session.commit()


def update_password(username, password_hash, must_change_password):
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.update_password(username, password_hash, must_change_password)
    session = get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        return False
    user.password_hash = password_hash
    user.must_change_password = 1 if must_change_password else 0
    session.commit()
    return True


def update_last_login(username):
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.update_last_login(username)
    session = get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is not None:
        user.last_login = datetime.now().isoformat()
        session.commit()


def set_active(username, is_active):
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.set_active(username, is_active)
    session = get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is not None:
        user.is_active = 1 if is_active else 0
        session.commit()


def set_role(username, role):
    if PG_MODE:
        from munshi.pg.services import user_service as pg_users
        return pg_users.set_role(username, role)
    session = get_session()
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is not None:
        user.role = role
        session.commit()
