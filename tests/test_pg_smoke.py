"""PG_MODE smoke tests — the DATABASE_URL-set analog of tests/test_smoke.py.

Drives the real Flask app (setup wizard, login, bill creation, ledger entry
+ mark-paid, payment recording) through the test client with app.PG_MODE
forced on, against a throwaway Organization in the live Supabase project —
not the real business's ORG_ID. Unlike SQLite's per-test fresh-file trick,
there's only one live Postgres project, so isolation comes from a
disposable per-test org (cascade-deleted at teardown) for org-scoped data,
plus a uniquely-suffixed test username (explicitly cleaned up) for the
non-org-scoped `users`/`login_failures` tables — same pattern already used
by every tests/test_pg_*.py file this session.

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

# Checked AFTER importing app.py, not before: app.py's own load_dotenv()
# call (override=True) populates DATABASE_URL from .env at import time even
# if the shell never exported it — checking earlier could wrongly skip in an
# environment that only has a .env file, not an exported shell var.
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE smoke tests')


@pytest.fixture()
def pg_client(tmp_path):
    from sqlalchemy import delete

    from munshi.pg import database as pg_database
    from munshi.pg.auth_models import User as PgUser
    from munshi.pg.models import Organization
    from munshi.pg.services.organization_service import create_organization
    from munshi.repositories import user_repository as _user_repository

    # user_repository.py's PG_MODE is its own module-level constant, not
    # re-derived from appmod.PG_MODE — and tests/test_smoke.py forces it to
    # False at collection time (runs for every test file in this process,
    # regardless of which test actually executes next), so it must be
    # re-enabled here explicitly or the auth-domain assertions below would
    # silently exercise SQLite instead of Postgres. Restored in teardown.
    _prev_user_repo_pg_mode = _user_repository.PG_MODE
    _user_repository.PG_MODE = True

    # SQLite-side paths still get exercised incidentally (init_db() always
    # builds that schema too, remember_vehicle() etc. still write there) —
    # point them at a throwaway temp dir so a local test run never touches
    # the real bills.db, same reasoning as test_smoke.py's client fixture.
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
    org = create_organization(session, f'PG Smoke Test Org {suffix}')
    session.commit()
    org_id = str(org.id)
    username = f'_pgtest_{suffix}'

    appmod.PG_MODE = True
    appmod.ORG_ID = org_id
    os.environ['MUNSHI_ORGANIZATION_ID'] = org_id  # user_service._org_id() reads this directly

    appmod.init_db()
    appmod.app.config.update(TESTING=True)
    client = appmod.app.test_client()

    yield client, username

    session.execute(delete(PgUser).where(PgUser.username == username))
    session.execute(delete(Organization).where(Organization.id == org.id))
    session.commit()
    pg_database.remove_session()
    appmod.PG_MODE = False
    appmod.ORG_ID = None
    _user_repository.PG_MODE = _prev_user_repo_pg_mode


def _csrf(client):
    # Both /setup and /login call session.clear() on success (wipes any
    # previously-seeded csrf_token along with everything else), so a fresh
    # GET is needed here every time, not just before the first POST in a
    # test — otherwise this reads back '' and the next POST 400s on CSRF
    # mismatch against whatever token _seed_csrf_token freshly generates
    # during that same request.
    client.get('/dashboard')
    with client.session_transaction() as sess:
        return sess.get('csrf_token', '')


def _setup(client, username, password, company='PG Smoke Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def _login(client, username, password):
    client.get('/login')
    token = _csrf(client)
    return client.post('/login', data={
        'username': username, 'password': password, 'csrf_token': token,
    }, follow_redirects=False)


def test_setup_and_login_persist_to_postgres(pg_client):
    client, username = pg_client
    resp = _setup(client, username, 'Owner1234')
    assert resp.status_code == 302

    # A second client (simulating a fresh session after a "redeploy") can
    # still log in — proves the user row is actually in Postgres, not just
    # the current session.
    client.get('/logout')
    resp = _login(client, username, 'Owner1234')
    assert resp.status_code == 302
    assert '/login' not in resp.headers.get('Location', '')


def test_create_bill_and_view_it(pg_client):
    client, username = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/bill/new', data={
        'csrf_token': token, 'delivery_count': '1', 'bill_date': '2026-07-23',
        'recipient_name': 'PG Test Client', 'state_code': '09', 'reverse_charge': '1',
        'd_value_of_supply_0': '15000',
    }, follow_redirects=False)
    assert resp.status_code == 302
    bill_url = resp.headers['Location']

    view = client.get(bill_url)
    assert view.status_code == 200
    assert b'JL-0001' in view.data
    assert 'PG Test Client'.encode() in view.data


def test_ledger_entry_mark_paid_and_transporter_balance(pg_client):
    client, username = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    t_resp = client.post('/masters/transporter/add', data={
        'csrf_token': token, 'name': 'PG Test Transporter', 'mobile': '9999999999',
    }, follow_redirects=False)
    assert t_resp.status_code == 302

    masters = client.get('/masters')
    assert b'PG Test Transporter' in masters.data

    from munshi.pg import database as pg_database
    from munshi.pg.services.transporter_service import list_transporters
    session = pg_database.get_session()
    transporter = next(t for t in list_transporters(session) if t.name == 'PG Test Transporter')

    token = _csrf(client)
    le_resp = client.post('/ledger/new', data={
        'csrf_token': token, 'entry_date': '2026-07-23', 'gr_no': 'PGTEST001',
        'vehicle_no': 'UP80AB1234', 'freight': '10000', 'advance_cash': '2000',
        'transporter_id': str(transporter.id),
    }, follow_redirects=False)
    assert le_resp.status_code == 302
    le_url = le_resp.headers['Location']

    view = client.get(le_url)
    assert view.status_code == 200
    assert b'PGTEST001' in view.data

    le_id = le_url.rstrip('/').split('/')[-1]
    token = _csrf(client)
    paid_resp = client.post(f'/ledger/{le_id}/paid', data={
        'csrf_token': token, 'paid': '1', 'paid_amount': '8000', 'paid_mode': 'UPI',
    }, follow_redirects=False)
    assert paid_resp.status_code == 302

    balance_page = client.get(f'/payments/transporter/{transporter.id}')
    assert balance_page.status_code == 200
    # freight 10000 - advance_cash 2000 - paid 8000 = 0 owed
    assert b'0.00' in balance_page.data or b'\xe2\x82\xb90' in balance_page.data


def test_record_manual_payment_reduces_client_balance(pg_client):
    client, username = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    client.post('/bill/new', data={
        'csrf_token': token, 'delivery_count': '1', 'bill_date': '2026-07-23',
        'recipient_name': 'PG Payment Client', 'state_code': '09', 'reverse_charge': '1',
        'd_value_of_supply_0': '20000',
    }, follow_redirects=False)

    detail_before = client.get('/payments/client/PG Payment Client')
    assert detail_before.status_code == 200

    token = _csrf(client)
    pay_resp = client.post('/payments/add', data={
        'csrf_token': token, 'party_type': 'client', 'party_key': 'PG Payment Client',
        'amount': '5000', 'payment_date': '2026-07-23',
    }, follow_redirects=False)
    assert pay_resp.status_code == 302

    hub = client.get('/payments')
    assert hub.status_code == 200
