"""Bills domain completion — index (bills list), edit_bill, summary,
bill_client_paid, ready_to_bill (/to-bill), einvoice.json export, and the
recipient/vehicle autocomplete-memory tables (previously ZERO PG_MODE
handling). Part of "remove SQLite completely from the hosted app" (see
.claude/plans/streamed-giggling-crescent.md).

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
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE bills-completion tests')


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
    org = create_organization(session, f'PG Bills Completion Test Org {suffix}')
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


def _setup(client, username, password, company='PG Bills Completion Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def _new_bill_form(**overrides):
    form = {
        'delivery_count': '1', 'bill_date': '2026-07-20', 'recipient_name': 'PG Bills Test Client',
        'recipient_address': 'Test Address', 'recipient_gstin': '', 'state_code': '09',
        'trip_type': 'One Way', 'vehicle_no': 'up80bc0001', 'client_name': 'PG Bills Test Client',
        'hsn_sac': '996511', 'gst_pct': '5', 'reverse_charge': 'on',
        'd_gr_no_0': 'BILLGR001', 'd_value_of_supply_0': '10000', 'd_freight_rate_0': '10000',
    }
    form.update(overrides)
    return form


def test_new_bill_then_index_lists_it(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/bill/new', data=_new_bill_form(csrf_token=token), follow_redirects=False)
    assert resp.status_code == 302

    listing = client.get('/')
    assert listing.status_code == 200
    assert b'PG Bills Test Client' in listing.data

    search = client.get('/?q=PG Bills Test Client')
    assert b'PG Bills Test Client' in search.data


def test_new_bill_remembers_recipient_and_vehicle(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    client.post('/bill/new', data=_new_bill_form(csrf_token=token), follow_redirects=False)

    from munshi.pg import database as pg_database
    from munshi.pg.services.recipient_service import list_recipients
    from munshi.pg.services.vehicle_service import list_vehicles
    session = pg_database.get_session()
    recipients = list_recipients(session, org_id)
    vehicles = list_vehicles(session, org_id)
    assert any(r.name == 'PG Bills Test Client' for r in recipients)
    assert any(v.vehicle_no == 'UP80BC0001' for v in vehicles)

    new_bill_page = client.get('/bill/new')
    assert b'PG Bills Test Client' in new_bill_page.data
    assert b'UP80BC0001' in new_bill_page.data


def test_edit_bill_updates_and_shows_in_form(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/bill/new', data=_new_bill_form(csrf_token=token), follow_redirects=False)
    bill_id = int(resp.headers['Location'].rstrip('/').split('/')[-1])

    edit_get = client.get(f'/bill/{bill_id}/edit')
    assert edit_get.status_code == 200
    assert b'PG Bills Test Client' in edit_get.data

    token = _csrf(client)
    edit_post = client.post(f'/bill/{bill_id}/edit', data=_new_bill_form(
        csrf_token=token,
        recipient_name='PG Bills Edited Client', d_value_of_supply_0='12000', d_freight_rate_0='12000',
    ), follow_redirects=False)
    assert edit_post.status_code == 302

    from munshi.pg import database as pg_database
    from munshi.pg.models import Bill
    session = pg_database.get_session()
    bill = session.get(Bill, bill_id)
    assert bill.recipient_name == 'PG Bills Edited Client'
    assert float(bill.taxable_value) == 12000.0


def test_bill_einvoice_json_exports_real_fields(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/bill/new', data=_new_bill_form(csrf_token=token), follow_redirects=False)
    bill_id = int(resp.headers['Location'].rstrip('/').split('/')[-1])

    einv = client.get(f'/bill/{bill_id}/einvoice.json')
    assert einv.status_code == 200
    data = einv.get_json()
    assert data['DocDtls']['Dt'] == '20/07/2026'
    assert data['BuyerDtls']['LglNm'] == 'PG Bills Test Client'


def test_bill_client_paid_marks_and_unmarks(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/bill/new', data=_new_bill_form(csrf_token=token), follow_redirects=False)
    bill_id = int(resp.headers['Location'].rstrip('/').split('/')[-1])

    token = _csrf(client)
    mark_resp = client.post(f'/bill/{bill_id}/client-paid', data={
        'csrf_token': token, 'client_paid': 'on', 'client_paid_mode': 'Cash',
        'client_paid_amount': '10500', 'client_paid_date': '2026-07-22',
    }, follow_redirects=False)
    assert mark_resp.status_code == 302

    from munshi.pg import database as pg_database
    from munshi.pg.models import Bill, Payment
    session = pg_database.get_session()
    bill = session.get(Bill, bill_id)
    assert bill.client_paid is True
    assert float(bill.client_paid_amount) == 10500.0

    from sqlalchemy import select
    payment = session.execute(select(Payment).where(
        Payment.organization_id == org_id, Payment.reference == f'auto-paid:bill:{bill_id}',
    )).scalar_one()
    assert float(payment.amount) == 10500.0

    token = _csrf(client)
    unmark_resp = client.post(f'/bill/{bill_id}/client-paid', data={'csrf_token': token},
                              follow_redirects=False)
    assert unmark_resp.status_code == 302
    session2 = pg_database.get_session()
    assert session2.get(Bill, bill_id).client_paid is False
    remaining = session2.execute(select(Payment).where(
        Payment.organization_id == org_id, Payment.reference == f'auto-paid:bill:{bill_id}',
    )).scalar_one_or_none()
    assert remaining is None


def test_summary_post_renders_selected_bills(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/bill/new', data=_new_bill_form(csrf_token=token), follow_redirects=False)
    bill_id = int(resp.headers['Location'].rstrip('/').split('/')[-1])

    listing = client.get('/summary')
    assert listing.status_code == 200

    from munshi.pg import database as pg_database
    from munshi.pg.models import Bill
    session = pg_database.get_session()
    bill_no = session.get(Bill, bill_id).bill_no

    token = _csrf(client)
    view = client.post('/summary', data={'csrf_token': token, 'bill_ids': [str(bill_id)]}, follow_redirects=False)
    assert view.status_code == 200
    # summary_view.html is a delivery-line-item sheet (SR/DEL NO./BILL NO./
    # VALUE OF SUPPLY columns) — it never prints the client name, only the
    # allocated bill number and per-delivery amounts.
    assert bill_no.encode() in view.data
    assert b'10,000.00' in view.data or b'10000' in view.data


def test_ready_to_bill_shows_pod_received_unbilled_trips(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.ledger_service import create_ledger_entry
    session = pg_database.get_session()
    entry = create_ledger_entry(
        session, org_id, entry_date=date.today(), gr_no='PGREADYTOBILL1',
        vehicle_no='UP80RB0001', station='Lucknow', freight=9000,
    )
    entry.pod_received = True
    session.commit()

    resp = client.get('/to-bill')
    assert resp.status_code == 200
    assert b'PGREADYTOBILL1' in resp.data

    token = _csrf(client)
    new_bill_from_ledger = client.get(f'/bill/new?from_ledger={entry.id}')
    assert new_bill_from_ledger.status_code == 200
