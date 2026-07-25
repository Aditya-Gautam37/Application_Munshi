"""Challan route + service tests — the first slice of the "finish moving
everything to Postgres" phase (see .claude/plans/streamed-giggling-crescent.md).
Covers: manual challan creation, list, view/edit, the auto-created-ledger-
entry-on-first-save-out-of-draft link, driver upsert, and that audit
entries actually land in Postgres now (the gap found and fixed this phase).

Route-level (not just service-level) on purpose — every real bug found
this session (CSRF re-seeding, bigint/varchar type mismatches) only
surfaced at the route/integration level, not in isolated service tests.

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
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE challan tests')


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
    org = create_organization(session, f'PG Challan Test Org {suffix}')
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


def _setup(client, username, password, company='PG Challan Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def test_manual_challan_create_view_edit_creates_ledger_link(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    new_resp = client.post('/challan/new', data={'csrf_token': token}, follow_redirects=False)
    assert new_resp.status_code == 302
    challan_url = new_resp.headers['Location']
    challan_id = challan_url.rstrip('/').split('/')[-1]

    # A freshly created draft has an auto-allocated LR number and shows up
    # in the list once it exists (list itself needs >=1 row to not redirect).
    view = client.get(challan_url)
    assert view.status_code == 200

    token = _csrf(client)
    edit_resp = client.post(challan_url, data={
        'csrf_token': token, 'lr_no': '1', 'challan_date': '2026-07-24',
        'consignor_name': 'PG Test Consignor', 'consignee_name': 'PG Test Consignee',
        'truck_no': 'UP80CD5678', 'driver_name': 'Test Driver', 'driver_mobile': '9876543210',
        'weight_kg': '5000', 'to_city_state': 'Lucknow, UP', 'invoice_no': 'INV-001',
    }, follow_redirects=False)
    assert edit_resp.status_code == 302

    index = client.get('/challans')
    assert index.status_code == 200
    assert b'PG Test Consignee' in index.data

    # The auto-created ledger entry exists and is linked back on the challan.
    from munshi.pg import database as pg_database
    from munshi.pg.services.challan_service import get_challan
    from munshi.pg.services.ledger_service import get_ledger_entry
    session = pg_database.get_session()
    challan = get_challan(session, org_id, int(challan_id))
    assert challan.status == 'open'
    assert challan.ledger_entry_id is not None
    entry = get_ledger_entry(session, org_id, challan.ledger_entry_id)
    assert entry is not None
    assert entry.vehicle_no == 'UP80CD5678'
    assert entry.gr_no == '1'
    assert float(entry.mt_qty) == 5.0  # 5000kg / 1000

    # Editing again (already 'open') must NOT create a second ledger entry.
    token = _csrf(client)
    client.post(challan_url, data={
        'csrf_token': token, 'lr_no': '1', 'consignee_name': 'PG Test Consignee Updated',
    }, follow_redirects=False)
    session2 = pg_database.get_session()
    challan_after = get_challan(session2, org_id, int(challan_id))
    assert challan_after.ledger_entry_id == challan.ledger_entry_id  # unchanged, not a new one

    # Audit entries landed in Postgres (the gap this phase fixed) — at
    # least the create-on-first-save entry for both the challan and the
    # auto-created ledger entry.
    from munshi.pg.services.audit_service import get_audit_for
    challan_audit = get_audit_for(session2, org_id, 'challan', int(challan_id))
    assert len(challan_audit) >= 1
    ledger_audit = get_audit_for(session2, org_id, 'ledger_entry', challan.ledger_entry_id)
    assert len(ledger_audit) >= 1


def test_driver_upsert_updates_name_on_repeat_mobile(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.driver_service import get_or_create_driver, list_drivers
    session = pg_database.get_session()

    mobile1 = get_or_create_driver(session, org_id, 'First Name', '9998887770')
    session.commit()
    assert mobile1 == '9998887770'

    get_or_create_driver(session, org_id, 'Updated Name', '9998887770')
    session.commit()

    drivers = list_drivers(session, org_id)
    assert len(drivers) == 1
    assert drivers[0].name == 'Updated Name'

    # Too-short mobile is a silent no-op, matching the SQLite original.
    result = get_or_create_driver(session, org_id, 'Bad', '123')
    assert result is None
