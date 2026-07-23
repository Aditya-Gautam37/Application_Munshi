"""Postgres (Supabase) engine/session for the multi-tenant stack.

Mirrors the shape of munshi/database/engine.py (bind/get_session/
remove_session) but is a fully separate module-level engine — never share a
process-global engine between this and the SQLite path; they must never
point at the same database.

RLS enforcement note: Supabase's own client libraries (PostgREST/supabase-py)
authenticate as the caller and let Postgres read `auth.uid()`/JWT claims
directly. Flask, talking to Postgres over a plain psycopg connection string
(service-role, bypassing PostgREST), has no JWT attached to the connection by
default — `set_tenant_context()` below fills that gap by setting the
`request.jwt.claims` GUC that the `current_org_id()` SQL helper (created in
the baseline Alembic migration) reads, for the lifetime of one transaction.
Call it at the start of every request, before any query, once JWT validation
(Phase 1) has populated `g.org_id`/`g.user_id`/`g.role`. Forgetting to call it
means RLS policies see no claims and every query returns zero rows (fails
closed, not open) — safe by default, but silently confusing to debug, so this
must be wired into a Flask before_request hook unconditionally in Phase 1.
"""
import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

_engine = None
_session_factory = None


def bind(database_url):
    """(Re)point this module's engine/session factory at `database_url`
    (a Supabase Postgres connection string, e.g.
    postgresql+psycopg://postgres:<password>@<host>:5432/postgres).
    Disposes any previous engine first.

    `prepare_threshold=None` disables psycopg3's automatic server-side
    prepared statements — required through Supabase's shared Transaction-
    mode pooler (PgBouncer), which can route successive queries on the same
    client-side connection to DIFFERENT backend Postgres connections. A
    prepared statement psycopg thinks it already created (client-side
    bookkeeping) may not exist on whichever backend PgBouncer picks next,
    surfacing as `psycopg.errors.DuplicatePreparedStatement` or "prepared
    statement does not exist" after enough queries. Discovered empirically
    (2026-07) via Phase 2's test suite after ~10 queries on one session."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(
        database_url, future=True, pool_pre_ping=True,
        connect_args={'prepare_threshold': None},
    )
    _session_factory = scoped_session(sessionmaker(bind=_engine, future=True))


def get_engine():
    if _engine is None:
        raise RuntimeError('Postgres engine not bound yet — call bind(database_url) first.')
    return _engine


def get_session():
    """A session scoped to the current thread. Call remove_session() at
    request teardown (Flask before_request/teardown_request, Phase 1)."""
    if _session_factory is None:
        raise RuntimeError('Postgres engine not bound yet — call bind(database_url) first.')
    return _session_factory()


def remove_session():
    if _session_factory is not None:
        _session_factory.remove()


def set_tenant_context(session, *, org_id, user_id=None, role=None):
    """Set the request.jwt.claims GUC AND downgrade to the `authenticated`
    Postgres role for this session's current transaction, so RLS policies
    (using current_org_id(), see the baseline migration) actually apply.

    Verified empirically against the real Supabase project (2026-07-17):
    DATABASE_URL's `postgres` user has rolbypassrls=true (Supabase's own
    pg_roles: postgres and service_role both bypass RLS; anon/authenticated
    do not) — connecting as `postgres` and setting request.jwt.claims alone
    is NOT enough, RLS silently no-ops and every query sees every tenant's
    rows. `SET LOCAL ROLE authenticated` is required every transaction, or
    this whole tenant-isolation model does nothing. SET LOCAL scopes both
    the role and the GUC to the current transaction only — neither leaks
    across pooled-connection reuse."""
    claims = {'org_id': str(org_id)}
    if user_id is not None:
        claims['sub'] = str(user_id)
    if role is not None:
        claims['role'] = role
    session.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {'claims': json.dumps(claims)},
    )
    session.execute(text('SET LOCAL ROLE authenticated'))
