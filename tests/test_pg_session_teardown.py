"""Proves and guards against the live-site outage found 2026-07-25: a
request that leaves the Postgres scoped_session in PendingRollbackError
state (e.g. any unhandled exception mid-query) used to poison every
SUBSEQUENT request handled by the same worker thread, because nothing
called munshi.pg.database.remove_session() at request teardown — despite
that module's own docstring saying to. Fixed by wiring remove_session()
into app.py's @app.teardown_request hook.

This test deliberately breaks the session (a raw invalid query, same as a
real crash would) WITHOUT going through the app, then makes a real request
through the Flask test client — if teardown isn't wired up, that next
request 500s exactly like the live site did; if it is, the broken session
gets discarded and the request succeeds normally.

Skips entirely (not fails) unless DATABASE_URL is set.
"""
import os
import sys
import uuid

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault("FLASK_SECRET_KEY", "smoke-test-secret-key-that-is-well-over-32-characters-long")
os.environ.pop("MUNSHI_REQUIRE_LICENSE", None)
os.environ.pop("LICENSE_SERVER_URL", None)

import app as appmod  # noqa: E402

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE teardown test')


@pytest.fixture()
def pg_client(tmp_path):
    from sqlalchemy import delete

    from munshi.pg import database as pg_database
    from munshi.pg.auth_models import User as PgUser
    from munshi.pg.models import Organization
    from munshi.pg.services.organization_service import create_organization
    from munshi.repositories import user_repository as _user_repository

    db_dir = tmp_path / "munshi"
    db_dir.mkdir(parents=True, exist_ok=True)
    appmod.DB_PATH = str(db_dir / "bills.db")
    appmod.BACKUP_DIR = str(db_dir / "backups")
    appmod.UPLOAD_DIR = str(db_dir / "uploads")
    os.makedirs(appmod.BACKUP_DIR, exist_ok=True)
    os.makedirs(appmod.UPLOAD_DIR, exist_ok=True)

    pg_database.bind(DATABASE_URL)
    session = pg_database.get_session()
    suffix = uuid.uuid4().hex[:8]
    org = create_organization(session, f'PG Teardown Test Org {suffix}')
    session.commit()
    org_id = str(org.id)
    username = f'_pgtest_{suffix}'

    appmod.PG_MODE = True
    appmod.ORG_ID = org_id
    os.environ['MUNSHI_ORGANIZATION_ID'] = org_id
    _prev_user_repo_pg_mode = _user_repository.PG_MODE
    _user_repository.PG_MODE = True

    appmod.init_db()
    appmod.app.config.update(TESTING=True)
    client = appmod.app.test_client()

    yield client, username, org_id

    session.rollback()
    try:
        session.execute(delete(PgUser).where(PgUser.username == username))
        session.execute(delete(Organization).where(Organization.id == org.id))
        session.commit()
    except Exception:
        session.rollback()
    pg_database.remove_session()
    appmod.PG_MODE = False
    appmod.ORG_ID = None
    _user_repository.PG_MODE = _prev_user_repo_pg_mode


def _csrf(client):
    client.get('/dashboard')
    with client.session_transaction() as sess:
        return sess.get('csrf_token', '')


def _setup(client, username, password, company='PG Teardown Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def test_broken_session_does_not_poison_the_next_request(pg_client):
    """Reproduces the live outage directly: within a single test-client
    'worker' (Flask's test client reuses the app's real scoped_session,
    same as gunicorn reuses one per worker thread), deliberately break the
    Postgres session with an invalid query, exactly as an unhandled
    exception mid-request would.

    The one request that inherits an already-broken session (broken OUTSIDE
    any request/response cycle here, to isolate the scenario) is expected
    to itself fail — teardown only runs AFTER a request, so it can't save
    that particular one. What must NOT happen is every request AFTER that
    also failing forever, which is exactly what the live site did: without
    remove_session() wired into teardown_request, nothing ever resets the
    thread-local scoped_session, so a single bad query poisons every
    subsequent request on that worker permanently."""
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    # Confirm the app is healthy before breaking anything.
    ok_before = client.get('/dashboard')
    assert ok_before.status_code == 200

    from sqlalchemy import text

    from munshi.pg import database as pg_database
    session = pg_database.get_session()
    try:
        session.execute(text('SELECT 1/0'))  # a real DB-level error, not a Python one
    except Exception:
        pass  # session is now in PendingRollbackError state, exactly like a real crash

    # This one request inherits the already-broken session and is expected
    # to itself error (Flask's TESTING mode propagates the raw exception
    # rather than returning a 500 Response, so catch it rather than
    # asserting a status code) — the real assertion is what happens next.
    try:
        client.get('/dashboard')
    except Exception:
        pass

    # The critical assertion: a request AFTER the failing one must succeed
    # normally. Without the teardown_request fix, this also fails — the
    # broken session was never discarded, so it cascades forever.
    resp = client.get('/dashboard')
    assert resp.status_code == 200, (
        'A broken Postgres session leaked past the request that broke it — '
        'the teardown_request hook is not cleaning up '
        'munshi.pg.database.remove_session() correctly.'
    )

    # And a second, unrelated page must also work — confirms the app is
    # genuinely recovered, not just accidentally surviving one lucky route.
    resp2 = client.get('/ledger')
    assert resp2.status_code == 200
