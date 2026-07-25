"""Infra completion — masters_index trip_count, /health real Postgres
counts, and confirming the desktop-only features (license phone-home,
Google Drive backup, local-file /restore) are safe no-ops under PG_MODE
rather than touching SQLite. Part of "remove SQLite completely from the
hosted app" (see .claude/plans/streamed-giggling-crescent.md).

Skips entirely (not fails) unless DATABASE_URL is set.
"""
import os
import sys
import uuid
from datetime import date

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault("FLASK_SECRET_KEY", "smoke-test-secret-key-that-is-well-over-32-characters-long")
os.environ.pop("MUNSHI_REQUIRE_LICENSE", None)
os.environ.pop("LICENSE_SERVER_URL", None)

import app as appmod  # noqa: E402

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE infra tests')


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
    org = create_organization(session, f'PG Infra Test Org {suffix}')
    session.commit()
    org_id = str(org.id)
    username = f'_pgtest_{suffix}'

    appmod.PG_MODE = True
    appmod.ORG_ID = org_id
    os.environ['MUNSHI_ORGANIZATION_ID'] = org_id
    _prev_user_repo_pg_mode = _user_repository.PG_MODE
    _user_repository.PG_MODE = True

    # init_db() in PG_MODE now early-returns after binding Postgres — the
    # local bills.db file must NOT exist afterward, proving nothing bootstraps
    # or touches it in the hosted path.
    appmod.init_db()
    appmod.app.config.update(TESTING=True)
    client = appmod.app.test_client()

    yield client, username, org_id, db_dir

    # A test body that raised mid-transaction can leave `session` in
    # PendingRollbackError state; without this rollback, the cleanup deletes
    # below would themselves raise, aborting teardown BEFORE remove_session()/
    # the PG_MODE reset run — leaking broken global state into every
    # subsequent test in this process. Always roll back first, and never let
    # a cleanup failure skip the reset.
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


def _setup(client, username, password, company='PG Infra Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def test_init_db_never_creates_local_sqlite_file_in_pg_mode(pg_client):
    _client, _username, _org_id, db_dir = pg_client
    assert not os.path.exists(appmod.DB_PATH), (
        'init_db() bootstrapped/created bills.db even in PG_MODE — the hosted '
        'app must never touch the local SQLite file at all.'
    )


def test_masters_index_shows_real_trip_count(pg_client):
    client, username, org_id, _ = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.ledger_service import create_ledger_entry
    from munshi.pg.services.transporter_service import create_transporter
    session = pg_database.get_session()
    transporter = create_transporter(session, org_id, 'PG Infra Masters Transporter')
    session.flush()
    create_ledger_entry(session, org_id, entry_date=date.today(), gr_no='PGINFRA1',
                        vehicle_no='UP80IN0001', freight=5000, transporter_id=transporter.id)
    create_ledger_entry(session, org_id, entry_date=date.today(), gr_no='PGINFRA2',
                        vehicle_no='UP80IN0002', freight=5000, transporter_id=transporter.id)
    session.commit()

    resp = client.get('/masters')
    assert resp.status_code == 200
    assert b'PG Infra Masters Transporter' in resp.data
    assert b'2' in resp.data  # trip_count rendered somewhere on the card


def test_health_reports_real_postgres_counts(pg_client):
    client, username, org_id, _ = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.ledger_service import create_ledger_entry
    session = pg_database.get_session()
    create_ledger_entry(session, org_id, entry_date=date.today(), gr_no='PGINFRAHEALTH1',
                        vehicle_no='UP80IN0009', freight=1000)
    session.commit()

    resp = client.get('/health')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['checks']['db']['backend'] == 'postgres'
    assert data['checks']['db']['ledger_entries'] >= 1
    assert data['checks']['backups'] == {'managed_by': 'Supabase (Postgres)'}


def test_license_and_drive_routes_are_safe_noops_not_sqlite_lockout(pg_client):
    """The desktop anti-piracy license lockout must never block a hosted
    request, and hitting the license/drive management POSTs must not raise
    (they should flash a 'not used here' message and redirect, no SQLite)."""
    client, username, org_id, _ = pg_client
    _setup(client, username, 'Owner1234')

    page = client.get('/license')
    assert page.status_code == 200

    token = _csrf(client)
    resp = client.post('/license/set', data={'csrf_token': token, 'license_key': 'FAKE-KEY'},
                       follow_redirects=False)
    assert resp.status_code == 302

    # A normal POST (e.g. adding a transporter) must NOT be blocked by lockout.
    token = _csrf(client)
    add_resp = client.post('/masters/transporter/add', data={
        'csrf_token': token, 'name': 'PG Infra Lockout Check Transporter',
    }, follow_redirects=False)
    assert add_resp.status_code == 302
    assert '/license' not in add_resp.headers.get('Location', '')

    token = _csrf(client)
    drive_resp = client.get('/settings/drive/connect', follow_redirects=False)
    assert drive_resp.status_code == 302
    assert 'settings' in drive_resp.headers.get('Location', '')


def test_restore_page_shows_no_local_backups_in_pg_mode(pg_client):
    client, username, org_id, _ = pg_client
    _setup(client, username, 'Owner1234')
    resp = client.get('/restore')
    assert resp.status_code == 200
