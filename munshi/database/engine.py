"""SQLAlchemy engine/session, used by domains as they migrate off raw sqlite3.

Deliberately NOT a replacement for legacy.get_db(): both point at the same
physical SQLite file. SQLite already runs in WAL mode specifically so more
than one connection can coexist safely (see legacy.get_db()'s own comment) —
that guarantee is what makes running the old raw-sqlite3 path and this new
SQLAlchemy path side-by-side, against the same bills.db, safe during the
migration.

`bind(db_path)` is called from app.py's init_db() every time it runs — which
is also the moment tests/test_smoke.py reassigns DB_PATH to a fresh temp path
before rebuilding the schema there. Rebinding here keeps this engine pointed
at whatever DB init_db() just (re)built, with no test-file changes needed.

Models are mapped onto a schema that init_db()'s raw-SQL CREATE TABLE / migration
logic already owns and creates — this module never calls Base.metadata.create_all().
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker

_engine = None
_session_factory = None


def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Mirrors legacy.get_db()'s PRAGMA calls, applied to every connection this
       engine's pool opens."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=8000')
    finally:
        cursor.close()


def bind(db_path):
    """(Re)point this module's engine/session factory at `db_path`. Disposes
       any previous engine first so stale pooled connections (e.g. to a prior
       test's temp DB) are never reused."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(f'sqlite:///{db_path}', future=True)
    event.listen(_engine, 'connect', _set_sqlite_pragma)
    _session_factory = scoped_session(sessionmaker(bind=_engine, future=True))


def get_engine():
    if _engine is None:
        raise RuntimeError('Database engine not bound yet — call bind(db_path) first '
                            '(app.py\'s init_db() does this on every run).')
    return _engine


def get_session():
    """A session scoped (via scoped_session) to the current thread — safe to
       call repeatedly within one request/thread and get the same session
       back. Call remove_session() at request teardown."""
    if _session_factory is None:
        raise RuntimeError('Database engine not bound yet — call bind(db_path) first '
                            '(app.py\'s init_db() does this on every run).')
    return _session_factory()


def remove_session():
    """Release the current thread's session back to the pool. Wired to Flask's
       teardown_request once create_app() exists (Phase 1)."""
    if _session_factory is not None:
        _session_factory.remove()
