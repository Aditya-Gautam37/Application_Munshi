"""Supabase Storage client — plain urllib.request calls to the Storage
REST API using the service-role key, matching this codebase's existing
convention (app.py's license-server phone-home client) rather than adding
a new HTTP-client dependency (requests/httpx aren't in requirements.txt).

One private bucket, `munshi-uploads`, keys prefixed
`{organization_id}/{domain}/...` mirroring the local UPLOAD_DIR subfolder
layout it replaces (extractions/<id>/NN_xxxx.ext, challans/..., pods/...,
ledger-pages/...). munshi/pg/models.py's docstrings on
ExtractedInvoice.file_name/Challan.source_image/etc. already say "Supabase
Storage object key" — this module is what makes that true.

Every Supabase REST call needs BOTH the `apikey` header (identifies the
project) AND `Authorization: Bearer <key>` (the actual credential) —
`Authorization` alone 400s. Confirmed empirically against the live project
while building this module: `apikey`-less requests fail even with a valid
service-role bearer token.
"""
import json
import os
import urllib.error
import urllib.request

BUCKET = 'munshi-uploads'


def _base_url():
    # .strip() before .rstrip('/'): a trailing newline (e.g. from
    # copy-pasting the value into Render's env var dashboard) isn't a '/',
    # so rstrip('/') alone wouldn't remove it — and a URL/header value with
    # an embedded '\n' fails outright (see _service_key()'s comment).
    url = os.environ.get('SUPABASE_URL', '').strip().rstrip('/')
    if not url:
        raise RuntimeError('SUPABASE_URL is not set.')
    return url


def _service_key():
    # Real bug hit in production (2026-07-25): SUPABASE_SERVICE_ROLE_KEY had
    # a trailing '\n' in Render's env var dashboard (likely from a
    # copy-paste). Python's http.client rejects any header value containing
    # a newline outright — "Invalid header value b'...key...\n'" — which
    # broke every Supabase Storage upload (challan/invoice/POD photos).
    # .strip() here makes this class of copy-paste whitespace bug
    # impossible regardless of how the env var gets set.
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not key:
        raise RuntimeError('SUPABASE_SERVICE_ROLE_KEY is not set.')
    return key


def _auth_headers():
    key = _service_key()
    return {'apikey': key, 'Authorization': f'Bearer {key}'}


def upload_bytes(key, data, content_type='application/octet-stream'):
    """Uploads (or overwrites, x-upsert) an object at `key`. Returns `key`
    unchanged, for call sites that want to store it immediately after."""
    url = f'{_base_url()}/storage/v1/object/{BUCKET}/{key}'
    req = urllib.request.Request(url, data=data, method='POST', headers={
        **_auth_headers(),
        'Content-Type': content_type,
        'x-upsert': 'true',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Storage upload failed for {key}: {e.code} {e.read().decode()[:300]}') from e
    return key


def download_bytes(key):
    url = f'{_base_url()}/storage/v1/object/{BUCKET}/{key}'
    req = urllib.request.Request(url, headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Storage download failed for {key}: {e.code}') from e


def get_signed_url(key, expires_in=900):
    """Temporary public URL for `key` (private bucket), valid for
    `expires_in` seconds — used to serve files to the browser without
    proxying bytes through Flask (matters much less on Render than it
    would on a serverless host, but it's still the right shape: no reason
    to hold a Flask worker busy streaming a photo)."""
    url = f'{_base_url()}/storage/v1/object/sign/{BUCKET}/{key}'
    body = json.dumps({'expiresIn': expires_in}).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={
        **_auth_headers(),
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Storage sign failed for {key}: {e.code} {e.read().decode()[:300]}') from e
    signed_path = result.get('signedURL') or result.get('signedUrl')
    if not signed_path:
        raise RuntimeError(f'Storage sign response missing signedURL for {key}: {result}')
    return f'{_base_url()}/storage/v1{signed_path}'


def delete_object(key):
    """Best-effort — matches the os.remove()-style callers this replaces,
    which don't treat 'already gone' as an error."""
    url = f'{_base_url()}/storage/v1/object/{BUCKET}/{key}'
    req = urllib.request.Request(url, method='DELETE', headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError:
        pass
