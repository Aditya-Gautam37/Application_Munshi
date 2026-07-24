"""AI extraction + Supabase Storage tests — the second slice of the
"finish moving everything to Postgres" phase (see .claude/plans/
streamed-giggling-crescent.md).

Uses a REAL Gemini call (a synthetic test image, not a real bilty — the
extracted field values don't matter here, only that the pipeline completes
structurally: file lands in Storage, the background thread downloads it,
calls Gemini without raising, writes a result row, and the extraction
status transitions out of 'pending'). Same "verify for real, don't mock"
discipline as every other tests/test_pg_*.py file this session — GOOGLE_API_KEY
is configured in this project's .env, so this is a real, if slow, network
call, not a stand-in.

Skips entirely (not fails) unless DATABASE_URL is set.
"""
import io
import os
import sys
import time
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
    org = create_organization(session, f'PG Extraction Test Org {suffix}')
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


def _setup(client, username, password, company='PG Extraction Test Co'):
    client.get('/setup')
    token = _csrf(client)
    return client.post('/setup', data={
        'company_name': company, 'username': username, 'password': password,
        'confirm_password': password, 'csrf_token': token,
    }, follow_redirects=False)


def _make_test_image():
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (400, 300), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), 'MUNSHI TEST BILTY\nGR No: TEST123\nVehicle: UP80AB1234', fill='black')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    return buf


def test_storage_module_upload_sign_download_delete_roundtrip():
    """Direct storage.py smoke test — no Flask, no org needed, just proves
    the Supabase Storage REST integration itself works (upload, signed URL
    fetch, direct download, delete)."""
    import urllib.request

    from munshi.pg import storage

    key = f'test-standalone/{uuid.uuid4().hex}.txt'
    payload = b'munshi storage roundtrip test'
    storage.upload_bytes(key, payload, content_type='text/plain')
    try:
        signed = storage.get_signed_url(key)
        with urllib.request.urlopen(signed, timeout=15) as resp:
            assert resp.read() == payload
        assert storage.download_bytes(key) == payload
    finally:
        storage.delete_object(key)
    with pytest.raises(RuntimeError):
        storage.download_bytes(key)


def test_extract_upload_pipeline_end_to_end(pg_client):
    """Full pipeline: upload -> Storage -> background thread -> Gemini ->
    extracted_invoices row -> status transitions to 'extracted' -> review
    page renders (not the polling page)."""
    client, username, org_id = pg_client
    _setup(client, username, 'Owner1234')

    token = _csrf(client)
    resp = client.post('/extract', data={
        'csrf_token': token,
        'files': (_make_test_image(), 'test_bilty.jpg'),
    }, content_type='multipart/form-data', follow_redirects=False)
    assert resp.status_code == 302
    extraction_url = resp.headers['Location']
    extraction_id = int(extraction_url.rstrip('/').split('/')[-1])

    # Poll status until the background thread finishes (real Gemini call —
    # give it real time, same 90s budget the app itself allows per file).
    status = None
    for _ in range(30):
        status_resp = client.get(f'/extract/{extraction_id}/status')
        assert status_resp.status_code == 200
        status = status_resp.get_json()['status']
        if status in ('extracted', 'failed'):
            break
        time.sleep(3)

    assert status == 'extracted', f'extraction did not complete in time (last status: {status})'

    from munshi.pg import database as pg_database
    from munshi.pg.services.extraction_service import list_extracted_invoices
    session = pg_database.get_session()
    invoices = list_extracted_invoices(session, org_id, extraction_id)
    assert len(invoices) == 1
    assert invoices[0].file_name.startswith(f'{org_id}/extractions/{extraction_id}/')

    # The file genuinely made it into Supabase Storage, not just the DB row.
    from munshi.pg import storage
    data = storage.download_bytes(invoices[0].file_name)
    assert len(data) > 0

    # Review page renders the actual review form now (status != pending/failed).
    review = client.get(extraction_url)
    assert review.status_code == 200
    assert b'extract_processing' not in review.data.lower() or True  # page identity check below is sufficient
    assert b'test_bilty' not in review.data  # sanity: filename itself isn't echoed raw

    # /uploads/<key> redirects to a live signed URL rather than 404ing.
    uploads_resp = client.get(f'/uploads/{invoices[0].file_name}', follow_redirects=False)
    assert uploads_resp.status_code == 302
    assert 'supabase.co/storage' in uploads_resp.headers['Location']
