"""Ledger domain completion — the ledger routes that had ZERO PG_MODE
handling before this slice (ledger_index, check-gr, POD marking incl.
Supabase Storage for the photo, amounts editing, bulk-pod, bulk-paid,
duplicate). Part of "remove SQLite completely from the hosted app" (see
.claude/plans/streamed-giggling-crescent.md).

Skips entirely (not fails) unless DATABASE_URL is set.
"""
import io
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
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE ledger-completion tests')


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
    org = create_organization(session, f'PG Ledger Completion Test Org {suffix}')
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


def _setup(client, username, password, company='PG Ledger Completion Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def _make_test_image():
    from PIL import Image
    img = Image.new('RGB', (200, 150), color='white')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    return buf


@pytest.fixture()
def seeded_entry(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.ledger_service import create_ledger_entry
    from munshi.pg.services.transporter_service import create_transporter
    session = pg_database.get_session()
    transporter = create_transporter(session, org_id, 'PG Ledger Completion Transporter')
    session.flush()
    entry = create_ledger_entry(
        session, org_id, entry_date=date.today(), gr_no='PGLEDCOMP001',
        vehicle_no='UP80LC0001', station='Kanpur', freight=15000, advance_cash=1000,
        transporter_id=transporter.id,
    )
    session.commit()
    return {'client': client, 'org_id': org_id, 'le_id': entry.id, 'transporter_id': transporter.id}


def test_ledger_index_lists_seeded_entry(seeded_entry):
    resp = seeded_entry['client'].get('/ledger')
    assert resp.status_code == 200
    assert b'PGLEDCOMP001' in resp.data


def test_ledger_index_status_filter(seeded_entry):
    resp = seeded_entry['client'].get('/ledger?status=paid')
    assert resp.status_code == 200
    assert b'PGLEDCOMP001' not in resp.data


def test_ledger_check_gr_finds_duplicate(seeded_entry):
    resp = seeded_entry['client'].get('/ledger/check-gr?gr_no=PGLEDCOMP001')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['duplicates']) == 1
    assert data['duplicates'][0]['vehicle_no'] == 'UP80LC0001'


def test_ledger_check_gr_no_match(seeded_entry):
    resp = seeded_entry['client'].get('/ledger/check-gr?gr_no=NOPE9999')
    assert resp.get_json() == {'duplicates': []}


def test_ledger_pod_with_photo_uploads_to_storage(seeded_entry):
    client, le_id = seeded_entry['client'], seeded_entry['le_id']
    token = _csrf(client)
    resp = client.post(f'/ledger/{le_id}/pod', data={
        'csrf_token': token, 'pod_received': 'on', 'pod_date': '2026-07-20',
        'delivery_date': '2026-07-21', 'shortage': '100', 'detention': '50',
        'pod_image': (_make_test_image(), 'pod.jpg'),
    }, content_type='multipart/form-data', follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg import database as pg_database
    from munshi.pg import storage
    from munshi.pg.services.ledger_service import get_ledger_entry
    session = pg_database.get_session()
    entry = get_ledger_entry(session, seeded_entry['org_id'], le_id)
    assert entry.pod_received is True
    assert str(entry.pod_date) == '2026-07-20'
    assert str(entry.delivery_date) == '2026-07-21'
    assert float(entry.shortage) == 100.0
    assert float(entry.detention) == 50.0
    assert entry.pod_image.startswith(f'{seeded_entry["org_id"]}/pods/')
    assert len(storage.download_bytes(entry.pod_image)) > 0


def test_ledger_pod_quick_tap_preserves_existing_adjustments(seeded_entry):
    """A quick 'Mark POD' tap from the list doesn't submit the adjustment
    fields at all — must fall back to the existing value, never zero them."""
    client, le_id, org_id = seeded_entry['client'], seeded_entry['le_id'], seeded_entry['org_id']
    token = _csrf(client)
    client.post(f'/ledger/{le_id}/pod', data={
        'csrf_token': token, 'pod_received': 'on', 'pod_date': '2026-07-20', 'shortage': '200',
    }, follow_redirects=False)

    token = _csrf(client)
    client.post(f'/ledger/{le_id}/pod', data={'csrf_token': token, 'pod_received': 'on'},
               follow_redirects=False)

    from munshi.pg import database as pg_database
    from munshi.pg.services.ledger_service import get_ledger_entry
    session = pg_database.get_session()
    entry = get_ledger_entry(session, org_id, le_id)
    assert float(entry.shortage) == 200.0


def test_ledger_amounts_updates_and_syncs_paid_mirror(seeded_entry):
    client, le_id, org_id = seeded_entry['client'], seeded_entry['le_id'], seeded_entry['org_id']

    token = _csrf(client)
    client.post(f'/ledger/{le_id}/paid', data={'csrf_token': token, 'paid': 'on'}, follow_redirects=False)

    token = _csrf(client)
    resp = client.post(f'/ledger/{le_id}/amounts', data={
        'csrf_token': token, 'freight': '18000', 'advance_cash': '2000',
        'advance_account': '0', 'diesel': '500',
    }, follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg import database as pg_database
    from munshi.pg.models import Payment
    from munshi.pg.services.ledger_service import get_ledger_entry
    session = pg_database.get_session()
    entry = get_ledger_entry(session, org_id, le_id)
    assert float(entry.freight) == 18000.0
    assert float(entry.diesel) == 500.0

    from sqlalchemy import select
    payment = session.execute(select(Payment).where(
        Payment.organization_id == org_id, Payment.reference == f'auto-paid:ledger:{le_id}',
    )).scalar_one()
    assert float(payment.amount) == 18000.0 - 2000.0 - 0.0 - 500.0


def test_ledger_bulk_pod_marks_only_unmarked(seeded_entry):
    client, le_id, org_id = seeded_entry['client'], seeded_entry['le_id'], seeded_entry['org_id']
    token = _csrf(client)
    resp = client.post('/ledger/bulk-pod', data={'csrf_token': token, 'ids': str(le_id)},
                       follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg import database as pg_database
    from munshi.pg.services.ledger_service import get_ledger_entry
    session = pg_database.get_session()
    entry = get_ledger_entry(session, org_id, le_id)
    assert entry.pod_received is True


def test_ledger_bulk_paid_creates_payment_row(seeded_entry):
    client, le_id, org_id = seeded_entry['client'], seeded_entry['le_id'], seeded_entry['org_id']
    token = _csrf(client)
    resp = client.post('/ledger/bulk-paid', data={'csrf_token': token, 'ids': str(le_id), 'mode': 'Cash'},
                       follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg import database as pg_database
    from munshi.pg.models import Payment
    from munshi.pg.services.ledger_service import get_ledger_entry
    session = pg_database.get_session()
    entry = get_ledger_entry(session, org_id, le_id)
    assert entry.paid is True

    from sqlalchemy import select
    payment = session.execute(select(Payment).where(
        Payment.organization_id == org_id, Payment.reference == f'auto-paid:ledger:{le_id}',
    )).scalar_one()
    assert float(payment.amount) == 15000.0 - 1000.0


def test_ledger_duplicate_clones_trip(seeded_entry):
    client, le_id, org_id = seeded_entry['client'], seeded_entry['le_id'], seeded_entry['org_id']
    token = _csrf(client)
    resp = client.post(f'/ledger/{le_id}/duplicate', data={'csrf_token': token}, follow_redirects=False)
    assert resp.status_code == 302

    from munshi.pg import database as pg_database
    from munshi.pg.services.ledger_service import list_ledger_entries
    session = pg_database.get_session()
    entries = list_ledger_entries(session, org_id)
    assert len(entries) == 2
    new_entry = next(e for e in entries if e.id != le_id)
    assert new_entry.gr_no == ''
    assert new_entry.vehicle_no == 'UP80LC0001'
    assert float(new_entry.freight) == 15000.0
    assert new_entry.pod_received is False
    assert new_entry.paid is False
