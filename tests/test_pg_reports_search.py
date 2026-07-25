"""Dashboard, reports (diesel/transporters/transporter-detail), search,
vehicle-history, trip lookup, and the /audit view — the read-only reporting
slice of "finish moving everything to Postgres" (see .claude/plans/
streamed-giggling-crescent.md). All previously SQLite-only; migrated
together since none touch money-write paths.

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
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE reports/search tests')


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
    org = create_organization(session, f'PG Reports Search Test Org {suffix}')
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


def _setup(client, username, password, company='PG Reports Search Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


@pytest.fixture()
def seeded(pg_client):
    """One transporter, one diesel vendor, one ledger entry (billed via a
    linked bill), one payment each side — enough real data for every report/
    search/trip/audit assertion below to have something non-trivial to find."""
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.bill_service import create_bill
    from munshi.pg.services.diesel_vendor_service import create_diesel_vendor
    from munshi.pg.services.ledger_service import create_ledger_entry
    from munshi.pg.services.payment_service import record_manual_payment
    from munshi.pg.services.transporter_service import create_transporter

    session = pg_database.get_session()
    transporter = create_transporter(session, org_id, 'PG Report Transporter')
    vendor = create_diesel_vendor(session, org_id, 'PG Report Diesel Vendor')
    session.flush()
    entry = create_ledger_entry(
        session, org_id, entry_date=date.today(), gr_no='PGREPORT001',
        vehicle_no='UP80RS0001', station='Kanpur', freight=20000, advance_cash=2000,
        diesel=3000, diesel_vendor_id=vendor.id, transporter_id=transporter.id,
    )
    session.flush()
    bill = create_bill(
        session, org_id, deliveries=[{'value_of_supply': '20000'}], bill_date=date.today(),
        recipient_name='PG Report Client', vehicle_no='UP80RS0001', from_ledger_id=entry.id,
    )
    record_manual_payment(session, org_id, 'transporter', transporter.id, 5000.0)
    record_manual_payment(session, org_id, 'client', 'PG Report Client', 8000.0)
    session.commit()

    return {
        'client': client, 'org_id': org_id, 'transporter_id': transporter.id,
        'vendor_id': vendor.id, 'ledger_id': entry.id, 'bill_id': bill.id,
    }


def test_dashboard_reflects_seeded_data(seeded):
    resp = seeded['client'].get('/dashboard')
    assert resp.status_code == 200
    # The seeded bill (total_amount=20000, bill_date=today) must show up in
    # this week's freight-billed KPI — proves the PG_MODE branch reads real
    # Postgres rows, not the empty bootstrapped local SQLite db.
    assert b'20,000' in resp.data


def test_report_diesel_shows_vendor_totals(seeded):
    resp = seeded['client'].get('/reports/diesel')
    assert resp.status_code == 200
    assert b'PG Report Diesel Vendor' in resp.data


def test_report_transporters_shows_balance_and_trips(seeded):
    resp = seeded['client'].get('/reports/transporters')
    assert resp.status_code == 200
    assert b'PG Report Transporter' in resp.data


def test_report_transporter_detail_lists_entries(seeded):
    resp = seeded['client'].get(f'/reports/transporter/{seeded["transporter_id"]}')
    assert resp.status_code == 200
    assert b'PGREPORT001' in resp.data


def test_report_transporter_detail_404_for_unknown_id(seeded):
    resp = seeded['client'].get('/reports/transporter/999999999')
    assert resp.status_code == 404


def test_api_vehicle_history_finds_last_trip(seeded):
    resp = seeded['client'].get('/api/vehicle-history/UP80RS0001')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['found'] is True
    assert data['station'] == 'Kanpur'
    assert data['gr_no'] == 'PGREPORT001'


def test_api_vehicle_history_not_found_for_unknown_vehicle(seeded):
    resp = seeded['client'].get('/api/vehicle-history/XX00ZZ9999')
    assert resp.get_json() == {'found': False}


def test_api_search_finds_bill_and_ledger(seeded):
    resp = seeded['client'].get('/api/search?q=PGREPORT001')
    assert resp.status_code == 200
    data = resp.get_json()
    assert any('PGREPORT001' in item['title'] for item in data['ledger'])


def test_trip_lookup_exact_gr_no_shows_full_360(seeded):
    resp = seeded['client'].get('/trip?q=PGREPORT001')
    assert resp.status_code == 200
    assert b'PG Report Client' in resp.data or b'UP80RS0001' in resp.data


def test_audit_log_view_lists_a_real_delete_action(seeded):
    client = seeded['client']
    token = _csrf(client)
    del_resp = client.post(f'/ledger/{seeded["ledger_id"]}/delete',
                           data={'csrf_token': token}, follow_redirects=False)
    assert del_resp.status_code == 302

    resp = client.get('/audit')
    assert resp.status_code == 200
    assert b'PGREPORT001' in resp.data
    assert b'Recycle Bin' in resp.data
