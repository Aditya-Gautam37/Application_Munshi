"""Supabase JWT verification — pure function, no Flask dependency.

Deliberately decoupled from any request/session machinery: this module's only
job is turning a Supabase-issued access token into trustworthy claims. How
those claims reach here (a browser JWT, a service script, a test) is the
caller's business, not this module's — see migration plan Phase 1 for why a
real login page isn't built yet.

Verified against the live project (2026-07): {SUPABASE_URL}/auth/v1/
.well-known/jwks.json serves an ES256 key, i.e. Supabase's own signing
algorithm, so JWKS-based verification (not a shared HS256 secret) is correct
here — PyJWT[crypto] is already pinned in requirements.txt for exactly this.
"""
import os
from functools import lru_cache

import jwt


class SupabaseAuthError(Exception):
    """Raised for any invalid/expired/unparseable token — callers decide how
    to respond (401, redirect to login, etc.); this module just refuses to
    hand back unverified claims."""


@lru_cache(maxsize=1)
def _jwks_client(supabase_url):
    """One PyJWKClient per (process, supabase_url) — it caches fetched keys
    internally, so building it repeatedly per-request would refetch JWKS on
    every call. lru_cache keyed on supabase_url means switching projects
    (e.g. across tests) still gets a fresh client instead of a stale one."""
    jwks_url = supabase_url.rstrip('/') + '/auth/v1/.well-known/jwks.json'
    return jwt.PyJWKClient(jwks_url)


def verify_supabase_jwt(token, supabase_url=None):
    """Verify a Supabase-issued access token and return its claims as a dict
    with at least {org_id, sub, role}. `org_id` is whatever the Auth Hook
    (not yet configured — see migration plan) injects as a custom claim;
    until that hook exists, `org_id` will be None for real Supabase tokens,
    which is expected and not this function's concern to fix.

    Raises SupabaseAuthError on any invalid/expired/malformed token or
    signature mismatch.
    """
    supabase_url = supabase_url or os.environ.get('SUPABASE_URL', '')
    if not supabase_url:
        raise SupabaseAuthError('SUPABASE_URL is not set — cannot locate the JWKS endpoint.')

    try:
        signing_key = _jwks_client(supabase_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=['ES256', 'RS256'],
            audience='authenticated',
            options={'require': ['exp', 'sub']},
        )
    except jwt.PyJWTError as e:
        raise SupabaseAuthError(f'Invalid Supabase token: {e}') from e

    return {
        'sub': claims.get('sub'),
        'org_id': claims.get('org_id'),
        'role': claims.get('role'),
        'email': claims.get('email'),
        'raw': claims,
    }
