"""Gate B — proves a REAL Supabase-issued access token (not a hand-rolled
stand-in) round-trips through munshi/pg/auth.py's verify_supabase_jwt() into
usable claims.

Creates a throwaway, pre-confirmed user via the Supabase Admin API (avoids
flakiness from email-confirmation settings), logs in as them via the normal
password grant to get a genuine end-user JWT, verifies it, then deletes the
user. Uses plain urllib.request, matching the convention already used by
app.py's license-server phone-home client (app.py:1553) — no new HTTP
dependency for this.

Skips (not fails) unless SUPABASE_URL/SUPABASE_ANON_KEY/
SUPABASE_SERVICE_ROLE_KEY are all set.
"""
import json
import os
import urllib.error
import urllib.request
import uuid

import pytest

from munshi.pg.auth import verify_supabase_jwt


def _http_json(url, body, headers, method='POST'):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={**headers, 'Content-Type': 'application/json'}, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else {})


@pytest.fixture()
def supabase_env():
    supabase_url = os.environ.get('SUPABASE_URL', '')
    anon_key = os.environ.get('SUPABASE_ANON_KEY', '')
    service_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if not (supabase_url and anon_key and service_key):
        pytest.skip(
            'SUPABASE_URL/SUPABASE_ANON_KEY/SUPABASE_SERVICE_ROLE_KEY not all set '
            '— skipping test that needs the live Supabase Auth API'
        )
    return supabase_url, anon_key, service_key


def test_real_supabase_jwt_verifies_and_decodes(supabase_env):
    supabase_url, anon_key, service_key = supabase_env
    email = f'munshi-test-{uuid.uuid4().hex[:12]}@example.com'
    password = f'Test-{uuid.uuid4().hex}!A1'

    admin_headers = {'apikey': service_key, 'Authorization': f'Bearer {service_key}'}
    status, body = _http_json(
        f'{supabase_url}/auth/v1/admin/users',
        {'email': email, 'password': password, 'email_confirm': True},
        admin_headers,
    )
    assert status in (200, 201), f'failed to create throwaway test user: {status} {body}'
    user_id = body['id']

    try:
        status, body = _http_json(
            f'{supabase_url}/auth/v1/token?grant_type=password',
            {'email': email, 'password': password},
            {'apikey': anon_key},
        )
        assert status == 200, f'failed to log in as throwaway test user: {status} {body}'
        access_token = body['access_token']

        claims = verify_supabase_jwt(access_token, supabase_url=supabase_url)
        assert claims['sub'] == user_id
        assert claims['email'] == email
    finally:
        _http_json(f'{supabase_url}/auth/v1/admin/users/{user_id}', None, admin_headers, method='DELETE')
