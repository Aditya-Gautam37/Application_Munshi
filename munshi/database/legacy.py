"""Raw sqlite3 connection helpers — relocated verbatim from app.py's original
get_db() / _close_request_db_conns(), parameterized on `db_path` instead of
closing over a module-level global.

app.py keeps a one-line wrapper:

    def get_db():
        return legacy.get_db(DB_PATH)

so that `DB_PATH` is read fresh on every call — this is what lets
tests/test_smoke.py reassign `appmod.DB_PATH` to a temp path and have every
subsequent get_db() call honor it, with no change to the test file.
"""
import sqlite3

from flask import g, has_request_context


def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # WAL lets the AI-extraction reader and a background writer coexist without
    # "database is locked"; the busy_timeout absorbs brief write locks.
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=8000')
    except sqlite3.Error:
        pass
    # Safety net against connection leaks: if we're inside a request, register
    # this connection so it is GUARANTEED to be closed at request teardown —
    # even when an exception skips the caller's explicit conn.close(). A leaked
    # SQLite connection keeps its WAL write-lock, which is the root cause of the
    # intermittent "database is locked" failures that build up over time.
    # Callers still close their own connections on the happy path (close() is
    # idempotent, so the teardown sweep is a no-op then). Background threads run
    # without a request context and keep managing their own connections as before.
    if has_request_context():
        conns = g.get('_db_conns')
        if conns is None:
            conns = []
            g._db_conns = conns
        conns.append(conn)
    return conn


def close_request_db_conns(exc):
    """Close any DB connection opened via get_db() during this request that the
       handler didn't already close (e.g. an exception unwound past its close()).
       close() is idempotent, so connections closed normally are unaffected."""
    for conn in g.pop('_db_conns', []) or []:
        try:
            conn.close()
        except Exception:
            pass
