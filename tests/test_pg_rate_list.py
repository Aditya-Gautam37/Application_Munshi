"""Rate-list master (freight_rates) — full CRUD editor + Excel import, the
last piece of the "finish moving everything to Postgres" phase (see
.claude/plans/streamed-giggling-crescent.md). Unlike every other domain
migrated this session, freight_rates had no PG_MODE service code at all
yet — though the table itself already existed live (created by
0001_baseline.py, just never wired to any route).

Skips entirely (not fails) unless DATABASE_URL is set.
"""
import io
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
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE rate-list tests')


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
    org = create_organization(session, f'PG Rate List Test Org {suffix}')
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


def _setup(client, username, password, company='PG Rate List Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def _make_rate_xlsx():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(['Customer Name', 'Party Code', 'Location', 'Dist TWY KM', 'Dist OWY KM',
               'LP TWY', 'LP OWY', 'Trolla TWY', 'Trolla OWY'])
    ws.append(['pg import client', 'PC1', 'kanpur', 250, 240, 15000, 14500, 18000, 17500])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_add_edit_delete_rate_row(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/rate-list/add', data={
        'csrf_token': token, 'customer_name': 'pg rate client', 'location': 'lucknow',
        'party_code': 'RC1', 'dist_twy_km': '300', 'dist_owy_km': '290',
        'lp_owy': '16000', 'lp_twy': '16500', 'trolla_owy': '19000', 'trolla_twy': '19500',
    }, follow_redirects=False)
    assert resp.status_code == 302

    listing = client.get('/rate-list')
    assert listing.status_code == 200
    assert b'PG RATE CLIENT' in listing.data
    assert b'LUCKNOW' in listing.data

    from munshi.pg import database as pg_database
    from munshi.pg.services.freight_rate_service import get_rate, list_rates
    session = pg_database.get_session()
    rows = list_rates(session, org_id)
    assert len(rows) == 1
    rid = rows[0].id
    assert float(rows[0].lp_owy) == 16000.0

    # Adding the same (customer_name, location) again must be rejected, not silently duplicated.
    token = _csrf(client)
    dup_resp = client.post('/rate-list/add', data={
        'csrf_token': token, 'customer_name': 'pg rate client', 'location': 'lucknow',
    }, follow_redirects=True)
    assert b'already exists' in dup_resp.data

    token = _csrf(client)
    update_resp = client.post(f'/rate-list/{rid}/update', data={
        'csrf_token': token, 'customer_name': 'pg rate client', 'location': 'lucknow',
        'party_code': 'RC1', 'dist_twy_km': '300', 'dist_owy_km': '290',
        'lp_owy': '17000', 'lp_twy': '16500', 'trolla_owy': '19000', 'trolla_twy': '19500',
    }, follow_redirects=False)
    assert update_resp.status_code == 302

    session2 = pg_database.get_session()
    updated = get_rate(session2, org_id, rid)
    assert float(updated.lp_owy) == 17000.0

    token = _csrf(client)
    del_resp = client.post(f'/rate-list/{rid}/delete', data={'csrf_token': token}, follow_redirects=False)
    assert del_resp.status_code == 302

    session3 = pg_database.get_session()
    assert get_rate(session3, org_id, rid) is None


def test_rate_list_search_filters_by_q(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.freight_rate_service import create_rate
    session = pg_database.get_session()
    create_rate(session, org_id, 'ALPHA TRANSPORT', 'DELHI')
    create_rate(session, org_id, 'BETA LOGISTICS', 'MUMBAI')
    session.commit()

    resp = client.get('/rate-list?q=ALPHA')
    assert resp.status_code == 200
    assert b'ALPHA TRANSPORT' in resp.data
    assert b'BETA LOGISTICS' not in resp.data


def test_excel_import_upserts_rows(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/settings/rate-list/upload', data={
        'csrf_token': token,
        'rate_file': (_make_rate_xlsx(), 'rates.xlsx'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    from munshi.pg import database as pg_database
    from munshi.pg.services.freight_rate_service import list_rates
    session = pg_database.get_session()
    rows = list_rates(session, org_id)
    assert len(rows) == 1
    assert rows[0].customer_name == 'PG IMPORT CLIENT'
    assert rows[0].location == 'KANPUR'
    assert rows[0].dist_twy_km == 250
    assert float(rows[0].lp_twy) == 15000.0

    # Re-importing the SAME (customer_name, location) must upsert, not duplicate.
    token = _csrf(client)
    client.post('/settings/rate-list/upload', data={
        'csrf_token': token,
        'rate_file': (_make_rate_xlsx(), 'rates.xlsx'),
    }, content_type='multipart/form-data', follow_redirects=True)
    session2 = pg_database.get_session()
    assert len(list_rates(session2, org_id)) == 1


def test_get_rate_list_used_by_bill_autofill(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.freight_rate_service import create_rate
    session = pg_database.get_session()
    create_rate(session, org_id, 'AUTOFILL CO', 'PATNA', lp_owy=12000)
    session.commit()

    resp = client.get('/bill/new')
    assert resp.status_code == 200
    assert b'AUTOFILL CO' in resp.data


def test_clear_rate_list_removes_all_rows(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    from munshi.pg import database as pg_database
    from munshi.pg.services.freight_rate_service import create_rate, list_rates
    session = pg_database.get_session()
    create_rate(session, org_id, 'TO BE CLEARED', 'NOIDA')
    session.commit()

    token = _csrf(client)
    resp = client.post('/settings/rate-list/clear', data={'csrf_token': token}, follow_redirects=False)
    assert resp.status_code == 302

    session2 = pg_database.get_session()
    assert list_rates(session2, org_id) == []
