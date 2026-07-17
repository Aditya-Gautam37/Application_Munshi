"""Auth & Setup business logic — relocated from app.py's inline route bodies.

Password hashing, login lockout, current_user()/current_user_role(), and
require_admin() are called from many not-yet-migrated routes elsewhere in
app.py (license, drive backup, reports, ledger, payments, restore) — app.py
keeps same-named thin wrappers around the functions here so every one of
those call sites is unaffected. See app.py's own comments at those wrappers.
"""
import base64
import hashlib
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta

from flask import flash, redirect, session, url_for

from munshi.repositories import user_repository as users


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(password):
    """PBKDF2-HMAC-SHA256 with 16-byte salt and 200k iterations (OWASP 2023)."""
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return base64.b64encode(salt + h).decode()


def verify_password(password, stored):
    try:
        raw = base64.b64decode(stored.encode())
    except Exception:
        return False
    if len(raw) < 32:
        return False
    salt, h = raw[:16], raw[16:]
    new_h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return secrets.compare_digest(h, new_h)


# ── Login brute-force throttling (persisted in the `login_failures` table) ────
# After _LOGIN_MAX_FAILURES wrong passwords within the window, the account is
# locked for the lockout period. Persisted (not in-memory) so a restart —
# e.g. after a Windows update, or the customer just closing/reopening the
# app — doesn't silently reset an active lockout. Every failed attempt is
# also written to the audit log for visibility.
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 15 * 60       # count failures within this rolling window
_LOGIN_LOCKOUT_SECONDS = 15 * 60      # lock the account this long once threshold is hit


def login_lockout_remaining(username):
    """Seconds left in the lockout for this username, or 0 if not locked."""
    if not username:
        return 0
    import app as _app

    now = datetime.now()
    cutoff = (now - timedelta(seconds=_LOGIN_WINDOW_SECONDS)).isoformat()
    conn = _app.get_db()
    try:
        # Drop stale failures for this username so the table doesn't grow
        # unbounded across an install's lifetime.
        conn.execute('DELETE FROM login_failures WHERE username = ? AND failed_at < ?',
                      (username, cutoff))
        conn.commit()
        rows = conn.execute(
            'SELECT failed_at FROM login_failures WHERE username = ? ORDER BY failed_at',
            (username,)
        ).fetchall()
    finally:
        conn.close()

    if len(rows) < _LOGIN_MAX_FAILURES:
        return 0
    last_failed = datetime.fromisoformat(rows[-1]['failed_at'])
    locked_until = last_failed + timedelta(seconds=_LOGIN_LOCKOUT_SECONDS)
    return max(0, int((locked_until - now).total_seconds()))


def record_login_failure(username):
    if not username:
        return
    import app as _app

    conn = _app.get_db()
    try:
        conn.execute('INSERT INTO login_failures (username, failed_at) VALUES (?, ?)',
                      (username, datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def clear_login_failures(username):
    if not username:
        return
    import app as _app

    conn = _app.get_db()
    try:
        conn.execute('DELETE FROM login_failures WHERE username = ?', (username,))
        conn.commit()
    finally:
        conn.close()


# ── Session-derived identity ─────────────────────────────────────────────────

def current_user():
    return session.get('user') or ''


def current_user_role():
    return session.get('role') or ''


def require_admin():
    """Return None if current user is admin, else a redirect response."""
    if current_user_role() != 'admin':
        flash('You need admin access for that action.')
        return redirect(url_for('dashboard'))
    return None


def is_setup_complete():
    import app as _app
    return _app._setup_complete()


# ── Setup wizard ──────────────────────────────────────────────────────────────

def complete_setup(form):
    """Validate + persist the first-run wizard. Returns (ok, error, gstin_note).
       On success, the caller (the route) still owns signing the session in —
       kept there since it's response/session plumbing, not a business rule."""
    import app as _app

    error = None
    if not form.company_name:
        error = 'Please enter your company / firm name.'
    elif not form.username:
        error = 'Please choose a username for your owner login.'
    elif len(form.password) < 4:
        error = 'Password must be at least 4 characters.'
    elif form.password != form.confirm_password:
        error = 'The two passwords do not match.'
    if error:
        return False, error, None

    gstin_note = None
    if form.gstin and len(form.gstin) != 15:
        gstin_note = 'Heads up: a GSTIN is normally 15 characters. Saved as entered.'

    if users.exists(form.username):
        return False, 'That username already exists. Pick another.', None

    _app.set_setting('supplier_name', form.company_name)
    _app.set_setting('supplier_gstin', form.gstin)
    _app.set_setting('supplier_pan', form.pan)
    _app.set_setting('supplier_address', form.address)
    _app.set_setting('supplier_state_code', form.state_code)
    _app.set_setting('supplier_phone', form.phone)

    users.create(form.username, hash_password(form.password), form.username,
                 'admin', must_change_password=False)

    conn = _app.get_db()
    try:
        _app.log_audit(conn, 'setup', 'user', None,
                        summary=f'Initial setup completed by {form.username}', user=form.username)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

    _app.set_setting('setup_complete', '1')
    return True, None, gstin_note


def load_demo_data(app_dir):
    """Copy data/seed_demo.db into the live DB. Returns (ok, message).
       Left on raw sqlite3 (via app.get_db()) rather than the ORM: it
       generically copies whichever tables exist in both DBs, which the
       per-table ORM models (Phase 0) aren't set up to do dynamically."""
    import app as _app

    demo_path = os.path.join(app_dir, 'data', 'seed_demo.db')
    try:
        bundle_dir = getattr(sys, '_MEIPASS', None)
    except Exception:
        bundle_dir = None
    if bundle_dir:
        bundled = os.path.join(bundle_dir, 'data', 'seed_demo.db')
        if os.path.exists(bundled):
            demo_path = bundled

    if not os.path.exists(demo_path):
        return False, 'Sample demo data is not available in this copy.'

    tables = ['settings', 'users', 'freight_rates', 'transporters',
              'diesel_vendors', 'recipients', 'vehicles', 'drivers',
              'bills', 'challans', 'ledger_entries', 'payments']
    try:
        src = sqlite3.connect(demo_path)
        src.row_factory = sqlite3.Row
        dst = _app.get_db()
        for t in tables:
            src_has = src.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
            dst_has = dst.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
            if not (src_has and dst_has):
                continue
            src_cols = [r['name'] for r in src.execute(f'PRAGMA table_info({t})').fetchall()]
            dst_cols = {r['name'] for r in dst.execute(f'PRAGMA table_info({t})').fetchall()}
            cols = [c for c in src_cols if c in dst_cols]
            if not cols:
                continue
            col_list = ','.join(f'"{c}"' for c in cols)
            placeholders = ','.join('?' for _ in cols)
            verb = 'INSERT OR REPLACE' if t in ('settings', 'users') else 'INSERT OR IGNORE'
            for row in src.execute(f'SELECT {col_list} FROM "{t}"').fetchall():
                dst.execute(
                    f'{verb} INTO "{t}" ({col_list}) VALUES ({placeholders})',
                    tuple(row[c] for c in cols))
        dst.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('setup_complete', '1'))
        dst.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('is_demo', '1'))
        dst.commit()
        dst.close()
        src.close()
    except Exception as e:
        _app.app.logger.warning(f'setup_demo failed: {e}')
        return False, 'Sorry, loading the sample demo data failed. Please try again or set up your own firm.'

    return True, None


# ── Login / logout ────────────────────────────────────────────────────────────

def attempt_login(username, password):
    """Returns one of:
       ('locked', wait_seconds)
       ('ok', user_row)
       ('failed', None)
    Handles lockout bookkeeping, last_login, and audit logging as side effects
    — mirrors the previous inline logic in app.py's login() route exactly."""
    import app as _app

    wait = login_lockout_remaining(username)
    if wait > 0:
        return 'locked', wait

    row = users.get_active_by_username(username)
    if row is not None and verify_password(password, row.password_hash):
        users.update_last_login(username)
        conn = _app.get_db()
        try:
            _app.log_audit(conn, 'login', 'user', None,
                            summary=f'User {row.username} signed in', user=row.username)
            conn.commit()
        finally:
            conn.close()
        clear_login_failures(username)
        return 'ok', row

    record_login_failure(username)
    conn = _app.get_db()
    try:
        _app.log_audit(conn, 'login_failed', 'user', None,
                        summary=f'Failed sign-in for "{username or "unknown"}"',
                        user=(username or 'unknown'))
        conn.commit()
    finally:
        conn.close()
    return 'failed', None


def log_logout(user):
    import app as _app
    if not user:
        return
    try:
        conn = _app.get_db()
        _app.log_audit(conn, 'logout', 'user', None,
                        summary=f'User {user} signed out', user=user)
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Change password ───────────────────────────────────────────────────────────

def change_password(username, old, new, confirm):
    """Returns (ok, message)."""
    if len(new) < 6:
        return False, 'New password must be at least 6 characters.'
    if new.lower() == (username or '').lower():
        return False, 'Your password cannot be the same as your username. Pick something different.'
    if new != confirm:
        return False, 'New passwords do not match.'
    row = users.get_by_username(username)
    if row is None or not verify_password(old, row.password_hash):
        return False, 'Current password is wrong.'
    users.update_password(username, hash_password(new), must_change_password=False)
    return True, 'Password updated.'


# ── User management (admin) ──────────────────────────────────────────────────

def list_users():
    return users.list_all()


def create_user(form):
    """Returns (ok, message)."""
    if not form.username:
        return False, 'Username is required.'
    if len(form.username) < 2:
        return False, 'Username must be at least 2 characters.'
    if users.exists(form.username):
        return False, f'User "{form.username}" already exists.'
    # First-login password = username
    users.create(form.username, hash_password(form.username), form.full_name,
                 form.role, must_change_password=True)
    _log_user_audit('create', form.username, f'Created user "{form.username}" ({form.role})')
    return True, (f'User "{form.username}" created. First-login password is '
                  f'"{form.username}" — they must change it.')


def reset_user_password(username):
    if not users.exists(username):
        return False, 'User not found.'
    users.update_password(username, hash_password(username), must_change_password=True)
    _log_user_audit('reset_password', username, f'Reset password for "{username}"')
    return True, (f'Password for "{username}" reset to their username. '
                  f'They will be forced to change it on next login.')


def deactivate_user(username):
    if username == current_user():
        return False, 'You cannot deactivate yourself.'
    users.set_active(username, False)
    _log_user_audit('deactivate', username, f'Deactivated user "{username}"')
    return True, f'User "{username}" deactivated. They can no longer sign in.'


def activate_user(username):
    users.set_active(username, True)
    _log_user_audit('activate', username, f'Re-activated user "{username}"')
    return True, f'User "{username}" re-activated.'


def change_user_role(username, new_role):
    if new_role not in ('admin', 'operator'):
        new_role = 'operator'
    if username == current_user() and new_role != 'admin':
        return False, 'You cannot demote yourself — promote another admin first.'
    users.set_role(username, new_role)
    _log_user_audit('change_role', username, f'Changed "{username}" role → {new_role}')
    return True, f'"{username}" is now {new_role}.'


def _log_user_audit(action, username, summary):
    import app as _app
    conn = _app.get_db()
    _app.log_audit(conn, action, 'user', 0, summary=summary)
    conn.commit()
    conn.close()
