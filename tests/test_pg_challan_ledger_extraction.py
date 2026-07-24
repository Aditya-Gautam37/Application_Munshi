"""Challan photo extraction (/challan/extract) and ledger-page extraction
(/ledger/extract) — the third slice of the "finish moving everything to
Postgres" phase (see .claude/plans/streamed-giggling-crescent.md). Both
reuse the Supabase Storage integration and patterns proven in
tests/test_pg_extraction.py.

Real Gemini calls (synthetic test images, same approach already proven to
work in test_pg_extraction.py — a simple PIL-drawn text image is enough
for Gemini to return a structured, if mostly-empty, result rather than
failing outright).

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
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='DATABASE_URL not set — skipping PG_MODE extraction tests')


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
    org = create_organization(session, f'PG Challan Extraction Test Org {suffix}')
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


def _setup(client, username, password, company='PG Challan Extraction Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def _make_test_image(lines):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (500, 400), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), '\n'.join(lines), fill='black')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    return buf


def test_challan_extract_upload_creates_challan_with_storage_photo(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/challan/extract', data={
        'csrf_token': token,
        'challan_file': (_make_test_image([
            'GOODS CONSIGNMENT NOTE', 'LR No: 555', 'Consignor: PG Test Consignor Co',
            'Consignee: PG Test Consignee Co', 'Truck No: UP80EF9012',
        ]), 'test_challan.jpg'),
    }, content_type='multipart/form-data', follow_redirects=False)
    assert resp.status_code == 302
    challan_url = resp.headers['Location']
    challan_id = int(challan_url.rstrip('/').split('/')[-1])

    from munshi.pg import database as pg_database
    from munshi.pg import storage
    from munshi.pg.services.challan_service import get_challan
    session = pg_database.get_session()
    challan = get_challan(session, org_id, challan_id)
    assert challan is not None
    assert challan.status == 'draft'
    assert challan.source_image is not None
    assert challan.source_image.startswith(f'{org_id}/challans/')

    # The photo genuinely made it into Storage.
    data = storage.download_bytes(challan.source_image)
    assert len(data) > 0

    view = client.get(challan_url)
    assert view.status_code == 200


def test_ledger_extract_upload_and_review_creates_ledger_entry(pg_client):
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/ledger/extract', data={
        'csrf_token': token,
        'file': (_make_test_image([
            'DRIVER LEDGER PAGE', 'GR No  Vehicle    Freight',
            '9001   UP80GH3456  15000',
        ]), 'test_ledger_page.jpg'),
    }, content_type='multipart/form-data', follow_redirects=False)
    assert resp.status_code == 302
    review_url = resp.headers['Location']
    le_ext_id = int(review_url.rstrip('/').split('/')[-1])

    review = client.get(review_url)
    assert review.status_code == 200

    from munshi.pg import database as pg_database
    from munshi.pg import storage
    from munshi.pg.services.ledger_extraction_service import get_ledger_extraction
    session = pg_database.get_session()
    extraction = get_ledger_extraction(session, org_id, le_ext_id)
    assert extraction is not None
    assert extraction.source_image.startswith(f'{org_id}/ledger-pages/')
    assert len(storage.download_bytes(extraction.source_image)) > 0

    # Submit the review form with exactly one row, mirroring what the real
    # template would post (row_count + per-row r_{i}_* fields).
    token = _csrf(client)
    submit = client.post(review_url, data={
        'csrf_token': token, 'row_count': '1', 'page_date': '2026-07-24',
        'r_0_include': 'on', 'r_0_gr_no': 'MANUAL9001', 'r_0_vehicle_no': 'up80gh3456',
        'r_0_freight': '15000', 'r_0_trip_type': 'One Way',
    }, follow_redirects=False)
    assert submit.status_code == 302

    from munshi.pg.services.ledger_extraction_service import get_ledger_extraction as _get
    from munshi.pg.services.ledger_service import list_ledger_entries
    session2 = pg_database.get_session()
    entries = list_ledger_entries(session2, org_id)
    assert len(entries) == 1
    assert entries[0].gr_no == 'MANUAL9001'
    assert entries[0].vehicle_no == 'UP80GH3456'
    assert float(entries[0].freight) == 15000.0

    used_extraction = _get(session2, org_id, le_ext_id)
    assert used_extraction.status == 'used'
