"""Recycle Bin (soft-delete / restore / purge) — the next slice of the
"finish moving everything to Postgres" phase (see .claude/plans/
streamed-giggling-crescent.md). Exercises the real delete routes
(bill/challan/ledger/payment) through to their PG_MODE archive branch, then
the generic /recycle-bin restore and purge routes, against the live
Supabase project.

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
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE recycle-bin tests')


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
    org = create_organization(session, f'PG Recycle Bin Test Org {suffix}')
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

    session.execute(delete(PgUser).where(PgUser.username == username))
    session.execute(delete(Organization).where(Organization.id == org.id))
    session.commit()
    pg_database.remove_session()
    appmod.PG_MODE = False
    appmod.ORG_ID = None
    _user_repository.PG_MODE = _prev_user_repo_pg_mode


def _csrf(client):
    client.get('/dashboard')
    with client.session_transaction() as sess:
        return sess.get('csrf_token', '')


def _setup(client, username, password, company='PG Recycle Bin Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def test_bill_delete_appears_in_bin_and_restores(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.bill_service import create_bill
    session = pg_database.get_session()
    bill = create_bill(
        session, org_id, deliveries=[{'value_of_supply': '1000'}], bill_date=date.today(),
        recipient_name='PG Recycle Bill Recipient',
    )
    session.commit()
    bill_id = bill.id

    token = _csrf(client)
    resp = client.post(f'/bill/{bill_id}/delete', data={'csrf_token': token}, follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg.models import Bill, BillArchive
    session2 = pg_database.get_session()
    assert session2.get(Bill, bill_id) is None
    archived = session2.get(BillArchive, bill_id)
    assert archived is not None
    assert archived.recipient_name == 'PG Recycle Bill Recipient'

    bin_page = client.get('/recycle-bin')
    assert bin_page.status_code == 200
    assert b'PG Recycle Bill Recipient' in bin_page.data

    token = _csrf(client)
    restore_resp = client.post(f'/recycle-bin/bill/{bill_id}/restore',
                               data={'csrf_token': token}, follow_redirects=False)
    assert restore_resp.status_code == 302

    session3 = pg_database.get_session()
    assert session3.get(BillArchive, bill_id) is None
    restored = session3.get(Bill, bill_id)
    assert restored is not None
    assert restored.recipient_name == 'PG Recycle Bill Recipient'


def test_payment_delete_and_purge_removed_forever(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.payment_service import record_manual_payment
    session = pg_database.get_session()
    payment = record_manual_payment(
        session, org_id, 'client', 'PG Recycle Payment Client', 500.0,
    )
    session.commit()
    pid = payment.id

    token = _csrf(client)
    resp = client.post(f'/payments/{pid}/delete', data={'csrf_token': token}, follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg.models import Payment, PaymentArchive
    session2 = pg_database.get_session()
    assert session2.get(Payment, pid) is None
    assert session2.get(PaymentArchive, pid) is not None

    token = _csrf(client)
    purge_resp = client.post(f'/recycle-bin/payment/{pid}/purge',
                             data={'csrf_token': token}, follow_redirects=False)
    assert purge_resp.status_code == 302

    session3 = pg_database.get_session()
    assert session3.get(PaymentArchive, pid) is None
    assert session3.get(Payment, pid) is None


def test_ledger_purge_nulls_linked_bill_fk(pg_client):
    """Purging a ledger entry that a bill still points at (bill.ledger_entry_id)
    must null that FK so the freed bill isn't left referencing a row that no
    longer exists anywhere — mirrors _RECYCLE['ledger']['purge_null']."""
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.bill_service import create_bill
    from munshi.pg.services.ledger_service import create_ledger_entry
    session = pg_database.get_session()
    entry = create_ledger_entry(
        session, org_id, entry_date=date.today(), gr_no='PGRECYCLE1',
        vehicle_no='UP80ZZ0001', freight=10000,
    )
    session.flush()
    bill = create_bill(
        session, org_id, deliveries=[{'value_of_supply': '1000'}], bill_date=date.today(),
        recipient_name='PG Recycle Ledger Bill', from_ledger_id=entry.id,
    )
    session.commit()
    le_id, bill_id = entry.id, bill.id

    from munshi.pg.models import Bill
    assert session.get(Bill, bill_id).ledger_entry_id == le_id

    token = _csrf(client)
    del_resp = client.post(f'/ledger/{le_id}/delete', data={'csrf_token': token}, follow_redirects=False)
    assert del_resp.status_code == 302

    token = _csrf(client)
    purge_resp = client.post(f'/recycle-bin/ledger/{le_id}/purge',
                             data={'csrf_token': token}, follow_redirects=False)
    assert purge_resp.status_code == 302

    session2 = pg_database.get_session()
    from munshi.pg.models import LedgerEntryArchive
    assert session2.get(LedgerEntryArchive, le_id) is None
    refreshed_bill = session2.get(Bill, bill_id)
    assert refreshed_bill is not None
    assert refreshed_bill.ledger_entry_id is None


def test_purge_requires_admin_role(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.payment_service import record_manual_payment
    session = pg_database.get_session()
    payment = record_manual_payment(session, org_id, 'client', 'PG Recycle Non Admin', 250.0)
    session.commit()
    pid = payment.id

    token = _csrf(client)
    client.post(f'/payments/{pid}/delete', data={'csrf_token': token}, follow_redirects=False)

    with client.session_transaction() as sess:
        sess['role'] = 'operator'

    token = _csrf(client)
    resp = client.post(f'/recycle-bin/payment/{pid}/purge',
                       data={'csrf_token': token}, follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg.models import PaymentArchive
    session2 = pg_database.get_session()
    assert session2.get(PaymentArchive, pid) is not None
