"""
Munshi License Server
=====================
A tiny, self-contained Flask app that decides whether each customer's Munshi
install is allowed to keep working. It is the "kill-switch" for non-payment.

WHAT IT DOES
  - Holds one row per customer (their license key, plan, and expiry date).
  - Answers the Munshi app's daily/weekly "is this key still active?" question
    (POST /verify) with active / grace / expired / suspended / not_found.
  - Lets the owner create keys and switch customers on/off — via a simple
    password-protected web dashboard (/admin) OR the JSON API (with a token).

WHAT IT DELIBERATELY DOES *NOT* DO
  - It never receives, stores, or sees any customer business data (no bilty,
    no ledger, no party names). The Munshi app only ever sends the license key,
    a truck COUNT (a number), and a version string. That is the whole point:
    the privacy promise stays intact.

RUN LOCALLY (for testing)
    cd license-server
    pip install -r requirements.txt
    MUNSHI_ADMIN_PASSWORD=changeme MUNSHI_ADMIN_TOKEN=secret-token python app.py
    open http://127.0.0.1:5090/admin

DEPLOY (when you go live) — see README.md.
"""

import os
import sqlite3
import secrets
import hmac
import calendar
from datetime import datetime, date
from functools import wraps

from flask import (Flask, request, jsonify, session, redirect, url_for,
                   render_template_string, flash, abort)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('MUNSHI_LICENSE_DB') or os.path.join(APP_DIR, 'licenses.db')

# ── Configuration (all via environment variables; never hard-code secrets) ──
ADMIN_TOKEN    = os.environ.get('MUNSHI_ADMIN_TOKEN', '').strip()     # for the JSON API / CLI
ADMIN_PASSWORD = os.environ.get('MUNSHI_ADMIN_PASSWORD', '').strip()  # for the web dashboard login
GRACE_DAYS     = int(os.environ.get('MUNSHI_GRACE_DAYS', '14'))       # writable "please renew" window after expiry
PORT           = int(os.environ.get('PORT', '5090'))

# Tiers → how many trucks the plan covers (informational; the app doesn't hard-block on it yet)
TIERS = {
    'starter': {'label': 'Starter · 1–3 trucks',   'max_trucks': 3},
    'growth':  {'label': 'Growth · 4–10 trucks',   'max_trucks': 10},
    'pro':     {'label': 'Pro · 11–30 trucks',     'max_trucks': 30},
    'fleet':   {'label': 'Fleet · 31+ trucks',     'max_trucks': 9999},
}

app = Flask(__name__)
# Session key for the admin dashboard login. Set LICENSE_FLASK_SECRET in production
# so logins survive a restart; otherwise a random per-boot key is used.
app.secret_key = os.environ.get('LICENSE_FLASK_SECRET') or secrets.token_urlsafe(32)
# Session-cookie hardening. SameSite=Lax blocks cross-site POSTs (CSRF defence for
# the dashboard actions); HttpOnly hides the cookie from JS; Secure is enabled in
# production (set LICENSE_HTTPS=1 once the server is behind HTTPS).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=(os.environ.get('LICENSE_HTTPS', '').strip() == '1'),
    MAX_CONTENT_LENGTH=64 * 1024,   # reject oversized request bodies (DoS guard)
)


# ── Database ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS licenses (
            license_key         TEXT PRIMARY KEY,
            customer_name       TEXT NOT NULL,
            phone               TEXT,
            tier                TEXT,
            max_trucks          INTEGER,
            expires_at          TEXT,          -- YYYY-MM-DD
            suspended           INTEGER DEFAULT 0,
            created_at          TEXT,
            notes               TEXT,
            last_seen           TEXT,
            last_truck_count    INTEGER,
            last_client_version TEXT
        );
        CREATE TABLE IF NOT EXISTS verify_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key    TEXT,
            at             TEXT,
            truck_count    INTEGER,
            client_version TEXT,
            status         TEXT,
            ip             TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_verify_key ON verify_log(license_key, at DESC);
    ''')
    conn.commit()
    conn.close()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now_iso():
    return datetime.now().isoformat(timespec='seconds')


def add_months(d, months):
    """Add whole months to a date, clamping the day to the month's length."""
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def gen_key():
    """Generate a MUNSHI-XXXX-XXXX-XXXX-XXXX key (unambiguous charset)."""
    charset = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'   # no 0/O/1/I/L to avoid read errors
    groups = ['-'.join(''.join(secrets.choice(charset) for _ in range(4)) for _ in range(4))]
    return 'MUNSHI-' + groups[0]


def unique_key(conn):
    for _ in range(20):
        k = gen_key()
        if not conn.execute('SELECT 1 FROM licenses WHERE license_key=?', (k,)).fetchone():
            return k
    raise RuntimeError('Could not generate a unique key')


def compute_status(rec):
    """Return (status, days_to_expiry). Statuses the Munshi client understands:
       active | grace | expired | suspended  (and not_found is handled at lookup)."""
    if rec['suspended']:
        return 'suspended', None
    try:
        exp = datetime.strptime(rec['expires_at'], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return 'expired', None
    dte = (exp - date.today()).days
    if dte >= 0:
        return 'active', dte
    if -dte <= GRACE_DAYS:
        return 'grace', dte
    return 'expired', dte


_STATUS_MESSAGE = {
    'active':    'License active.',
    'grace':     'Your license has expired — you are in the grace period. Please renew soon.',
    'expired':   'License expired. Munshi is now read-only until you renew. Your data is safe.',
    'suspended': 'License suspended. Please contact support / clear your dues.',
    'not_found': 'License key not recognised. Please check the key or contact support.',
}


def _log(conn, key, truck_count, cver, status):
    cur = conn.execute(
        'INSERT INTO verify_log (license_key, at, truck_count, client_version, status, ip) '
        'VALUES (?,?,?,?,?,?)',
        ((key or '')[:60], _now_iso(), _as_int(truck_count), (cver or '')[:40], status,
         (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:60]))
    # Backstop against a /verify flood filling the disk: every 5000 rows, trim the
    # log to the most recent 100k. (Also rate-limit /verify at nginx — see README.)
    if cur.lastrowid and cur.lastrowid % 5000 == 0:
        conn.execute('DELETE FROM verify_log WHERE id NOT IN '
                     '(SELECT id FROM verify_log ORDER BY id DESC LIMIT 100000)')


def _as_int(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    # Clamp to SQLite's signed-64-bit range so a hostile huge number on the
    # public /verify endpoint can't raise OverflowError (a 500 + connection leak).
    return n if -2**63 <= n < 2**63 else None


# ── Auth ────────────────────────────────────────────────────────────────────

def require_token(f):
    """Protect JSON admin endpoints with a bearer token (constant-time compare)."""
    @wraps(f)
    def wrapper(*a, **kw):
        if not ADMIN_TOKEN:
            return jsonify({'error': 'admin API not configured (set MUNSHI_ADMIN_TOKEN)'}), 503
        auth = request.headers.get('Authorization', '')
        token = auth[7:].strip() if auth.startswith('Bearer ') else ''
        if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
            return jsonify({'error': 'unauthorized'}), 401
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    """Protect the web dashboard with a session login."""
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get('admin'):
            return redirect(url_for('admin_login', next=request.path))
        return f(*a, **kw)
    return wrapper


# ── Public endpoint: the Munshi app calls this ──────────────────────────────

@app.route('/verify', methods=['POST'])
def verify():
    body = request.get_json(silent=True) or {}
    key = (body.get('license_key') or '').strip().upper()
    truck_count = body.get('truck_count')
    cver = body.get('client_version')

    conn = get_db()
    rec = conn.execute('SELECT * FROM licenses WHERE license_key=?', (key,)).fetchone()
    if not rec:
        _log(conn, key, truck_count, cver, 'not_found')
        conn.commit(); conn.close()
        return jsonify({'status': 'not_found', 'tier': None, 'max_trucks': None,
                        'expires_at': None, 'days_to_expiry': None,
                        'message': _STATUS_MESSAGE['not_found']})

    status, dte = compute_status(rec)
    conn.execute('UPDATE licenses SET last_seen=?, last_truck_count=?, last_client_version=? '
                 'WHERE license_key=?', (_now_iso(), _as_int(truck_count), (cver or '')[:40], key))
    _log(conn, key, truck_count, cver, status)
    conn.commit(); conn.close()

    return jsonify({
        'status':         status,
        'tier':           rec['tier'],
        'max_trucks':     rec['max_trucks'],
        'expires_at':     rec['expires_at'],
        'days_to_expiry': dte,
        'message':        _STATUS_MESSAGE.get(status, ''),
    })


@app.route('/health')
def health():
    try:
        conn = get_db()
        n = conn.execute('SELECT COUNT(*) FROM licenses').fetchone()[0]
        active = 0
        for r in conn.execute('SELECT * FROM licenses').fetchall():
            if compute_status(r)[0] in ('active', 'grace'):
                active += 1
        conn.close()
        return jsonify({'ok': True, 'licenses': n, 'active_or_grace': active,
                        'grace_days': GRACE_DAYS,
                        'admin_api': bool(ADMIN_TOKEN), 'admin_web': bool(ADMIN_PASSWORD)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)[:200]}), 500


# ── JSON admin API (token-protected) — for scripts / CLI ────────────────────

@app.route('/provision', methods=['POST'])
@require_token
def provision():
    body = request.get_json(silent=True) or {}
    name = (body.get('customer_name') or '').strip()
    if not name:
        return jsonify({'error': 'customer_name required'}), 400
    tier = (body.get('tier') or 'starter').strip().lower()
    if tier not in TIERS:
        return jsonify({'error': f'unknown tier; use one of {list(TIERS)}'}), 400
    max_trucks = _as_int(body.get('max_trucks')) or TIERS[tier]['max_trucks']

    if body.get('expiry_date'):
        expiry = str(body['expiry_date'])[:10]
        try:
            datetime.strptime(expiry, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'expiry_date must be YYYY-MM-DD'}), 400
    else:
        months = _as_int(body.get('months')) or 12
        expiry = add_months(date.today(), months).isoformat()

    conn = get_db()
    key = unique_key(conn)
    conn.execute('''INSERT INTO licenses
        (license_key, customer_name, phone, tier, max_trucks, expires_at,
         suspended, created_at, notes)
        VALUES (?,?,?,?,?,?,0,?,?)''',
        (key, name, (body.get('phone') or '').strip(), tier, max_trucks, expiry,
         _now_iso(), (body.get('notes') or '').strip()))
    conn.commit(); conn.close()
    return jsonify({'license_key': key, 'customer_name': name, 'tier': tier,
                    'max_trucks': max_trucks, 'expires_at': expiry})


def _mutate(key, fn):
    conn = get_db()
    rec = conn.execute('SELECT * FROM licenses WHERE license_key=?', (key,)).fetchone()
    if not rec:
        conn.close()
        return None
    result = fn(conn, rec)
    conn.commit(); conn.close()
    return result


@app.route('/license/<key>/suspend', methods=['POST'])
@require_token
def api_suspend(key):
    ok = _mutate(key.upper(), lambda c, r: c.execute(
        'UPDATE licenses SET suspended=1 WHERE license_key=?', (r['license_key'],)))
    return (jsonify({'ok': True, 'license_key': key.upper(), 'suspended': True})
            if ok is not None else (jsonify({'error': 'not found'}), 404))


@app.route('/license/<key>/reactivate', methods=['POST'])
@require_token
def api_reactivate(key):
    ok = _mutate(key.upper(), lambda c, r: c.execute(
        'UPDATE licenses SET suspended=0 WHERE license_key=?', (r['license_key'],)))
    return (jsonify({'ok': True, 'license_key': key.upper(), 'suspended': False})
            if ok is not None else (jsonify({'error': 'not found'}), 404))


@app.route('/license/<key>/extend', methods=['POST'])
@require_token
def api_extend(key):
    body = request.get_json(silent=True) or {}
    months = _as_int(body.get('months')) or 12

    def do(c, r):
        try:
            base = datetime.strptime(r['expires_at'], '%Y-%m-%d').date()
        except (TypeError, ValueError):
            base = date.today()
        base = max(base, date.today())   # extend from today if already lapsed
        new_exp = add_months(base, months).isoformat()
        c.execute('UPDATE licenses SET expires_at=? WHERE license_key=?', (new_exp, r['license_key']))
        return new_exp

    new_exp = _mutate(key.upper(), do)
    return (jsonify({'ok': True, 'license_key': key.upper(), 'expires_at': new_exp})
            if new_exp is not None else (jsonify({'error': 'not found'}), 404))


@app.route('/licenses', methods=['GET'])
@require_token
def api_list():
    conn = get_db()
    rows = conn.execute('SELECT * FROM licenses ORDER BY created_at DESC').fetchall()
    conn.close()
    out = []
    for r in rows:
        status, dte = compute_status(r)
        out.append({**dict(r), 'status': status, 'days_to_expiry': dte})
    return jsonify({'licenses': out})


# ── Web dashboard (session-protected) — for the owner ───────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if not ADMIN_PASSWORD:
        return ('<p style="font-family:sans-serif;max-width:600px;margin:3rem auto">'
                'Admin dashboard not configured. Set <code>MUNSHI_ADMIN_PASSWORD</code> '
                'and restart the server.</p>'), 503
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if hmac.compare_digest(pw, ADMIN_PASSWORD):
            session['admin'] = True
            # Only allow relative in-site redirects (block open-redirect phishing).
            nxt = request.args.get('next') or ''
            if not nxt.startswith('/') or nxt.startswith('//'):
                nxt = url_for('admin')
            return redirect(nxt)
        flash('Wrong password.')
    return render_template_string(LOGIN_HTML)


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))


@app.route('/admin')
@admin_required
def admin():
    conn = get_db()
    rows = conn.execute('SELECT * FROM licenses ORDER BY created_at DESC').fetchall()
    conn.close()
    lics = []
    for r in rows:
        status, dte = compute_status(r)
        lics.append({**dict(r), 'status': status, 'days_to_expiry': dte})
    counts = {'active': 0, 'grace': 0, 'expired': 0, 'suspended': 0}
    for l in lics:
        counts[l['status']] = counts.get(l['status'], 0) + 1
    return render_template_string(ADMIN_HTML, lics=lics, tiers=TIERS, counts=counts,
                                  today=date.today().isoformat(), grace=GRACE_DAYS)


@app.route('/admin/create', methods=['POST'])
@admin_required
def admin_create():
    name = (request.form.get('customer_name') or '').strip()
    if not name:
        flash('Customer name is required.')
        return redirect(url_for('admin'))
    tier = (request.form.get('tier') or 'starter').strip().lower()
    if tier not in TIERS:
        tier = 'starter'
    months = _as_int(request.form.get('months')) or 12
    expiry = add_months(date.today(), months).isoformat()
    conn = get_db()
    key = unique_key(conn)
    conn.execute('''INSERT INTO licenses
        (license_key, customer_name, phone, tier, max_trucks, expires_at,
         suspended, created_at, notes)
        VALUES (?,?,?,?,?,?,0,?,?)''',
        (key, name, (request.form.get('phone') or '').strip(), tier,
         TIERS[tier]['max_trucks'], expiry, _now_iso(),
         (request.form.get('notes') or '').strip()))
    conn.commit(); conn.close()
    flash(f'Created key {key} for {name} — valid until {expiry}.')
    return redirect(url_for('admin'))


@app.route('/admin/<key>/<action>', methods=['POST'])
@admin_required
def admin_action(key, action):
    key = key.upper()
    if action == 'suspend':
        _mutate(key, lambda c, r: c.execute('UPDATE licenses SET suspended=1 WHERE license_key=?', (key,)))
        flash(f'{key} suspended — that customer goes read-only on their next check.')
    elif action == 'reactivate':
        _mutate(key, lambda c, r: c.execute('UPDATE licenses SET suspended=0 WHERE license_key=?', (key,)))
        flash(f'{key} reactivated.')
    elif action in ('extend1', 'extend12'):
        months = 1 if action == 'extend1' else 12
        def do(c, r):
            try:
                base = datetime.strptime(r['expires_at'], '%Y-%m-%d').date()
            except (TypeError, ValueError):
                base = date.today()
            base = max(base, date.today())
            c.execute('UPDATE licenses SET expires_at=? WHERE license_key=?',
                      (add_months(base, months).isoformat(), key))
        _mutate(key, do)
        flash(f'{key} extended by {months} month(s).')
    else:
        flash('Unknown action.')
    return redirect(url_for('admin'))


# ── Templates (inline, no external files) ───────────────────────────────────

LOGIN_HTML = '''
<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Munshi License — Login</title>
<style>body{font-family:system-ui,sans-serif;background:#f4f5f7;display:flex;min-height:100vh;
align-items:center;justify-content:center;margin:0}.box{background:#fff;padding:2rem;border-radius:12px;
box-shadow:0 1px 4px rgba(0,0,0,.08);width:320px}h1{font-size:18px;margin:0 0 1rem}
input{width:100%;padding:.6rem;border:1px solid #ccc;border-radius:8px;box-sizing:border-box;font-size:15px}
button{width:100%;padding:.6rem;margin-top:.8rem;border:0;border-radius:8px;background:#3949ab;color:#fff;
font-size:15px;cursor:pointer}.msg{color:#b00;font-size:13px;margin:.5rem 0}</style>
<div class=box><h1>Munshi License — Owner Login</h1>
{% with m = get_flashed_messages() %}{% if m %}<div class=msg>{{ m[0] }}</div>{% endif %}{% endwith %}
<form method=post><input type=password name=password placeholder="Password" autofocus>
<button type=submit>Log in</button></form></div>
'''

ADMIN_HTML = '''
<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Munshi License — Customers</title>
<style>
body{font-family:system-ui,sans-serif;background:#f4f5f7;margin:0;color:#1a1a1a}
.wrap{max-width:1000px;margin:0 auto;padding:1.5rem}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem}
h1{font-size:20px;margin:0}a.out{font-size:13px;color:#555}
.cards{display:flex;gap:10px;margin-bottom:1.2rem;flex-wrap:wrap}
.card{background:#fff;border-radius:10px;padding:.7rem 1rem;min-width:90px}
.card .n{font-size:22px;font-weight:600}.card .l{font-size:12px;color:#666}
.panel{background:#fff;border-radius:12px;padding:1.2rem;margin-bottom:1.2rem}
h2{font-size:15px;margin:0 0 .8rem}
form.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}
label{font-size:12px;color:#555;display:block}
input,select{padding:.5rem;border:1px solid #ccc;border-radius:8px;font-size:14px}
button{padding:.5rem .9rem;border:0;border-radius:8px;background:#3949ab;color:#fff;font-size:14px;cursor:pointer}
button.g{background:#2e7d32}button.r{background:#c62828}button.o{background:#ef6c00}
table{width:100%;border-collapse:collapse;font-size:13px;background:#fff;border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:.6rem .7rem;border-bottom:1px solid #eee}
th{background:#fafafa;font-size:12px;color:#666}
code{background:#f1f1f4;padding:2px 6px;border-radius:6px;font-size:12px}
.pill{padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.s-active{background:#e6f4ea;color:#1e7e34}.s-grace{background:#fff3cd;color:#8a6d00}
.s-expired{background:#fde8e8;color:#b02020}.s-suspended{background:#eee;color:#555}
.acts{display:flex;gap:5px;flex-wrap:wrap}.acts form{display:inline}
.flash{background:#e6f0ff;border:1px solid #b5d0f5;padding:.7rem 1rem;border-radius:10px;margin-bottom:1rem;font-size:14px}
.muted{color:#888;font-size:12px}
</style>
<div class=wrap>
<div class=top><h1>Munshi — Customers &amp; Licenses</h1><a class=out href="{{ url_for('admin_logout') }}">Log out</a></div>
{% with m = get_flashed_messages() %}{% if m %}<div class=flash>{{ m[0] }}</div>{% endif %}{% endwith %}
<div class=cards>
  <div class=card><div class=n>{{ counts.active }}</div><div class=l>Active</div></div>
  <div class=card><div class=n>{{ counts.grace }}</div><div class=l>Grace</div></div>
  <div class=card><div class=n>{{ counts.expired }}</div><div class=l>Expired</div></div>
  <div class=card><div class=n>{{ counts.suspended }}</div><div class=l>Suspended</div></div>
</div>

<div class=panel>
  <h2>Add a new customer</h2>
  <form class=row method=post action="{{ url_for('admin_create') }}">
    <div><label>Customer name</label><input name=customer_name required placeholder="e.g. Sharma Transport"></div>
    <div><label>Phone</label><input name=phone placeholder="WhatsApp/phone"></div>
    <div><label>Plan</label><select name=tier>
      {% for k,v in tiers.items() %}<option value="{{ k }}">{{ v.label }}</option>{% endfor %}
    </select></div>
    <div><label>Valid for (months)</label><input name=months type=number value=12 min=1 max=60 style="width:120px"></div>
    <div><button type=submit>Create key</button></div>
  </form>
  <p class=muted>The key (MUNSHI-XXXX-XXXX-XXXX-XXXX) appears in the green bar. Send it to the customer; they paste it in Munshi → License.</p>
</div>

<table>
<tr><th>Customer</th><th>Key</th><th>Plan</th><th>Status</th><th>Expires</th><th>Last seen</th><th>Trucks</th><th>Actions</th></tr>
{% for l in lics %}
<tr>
  <td>{{ l.customer_name }}<div class=muted>{{ l.phone or '' }}</div></td>
  <td><code>{{ l.license_key }}</code></td>
  <td>{{ tiers.get(l.tier, {}).get('label', l.tier) }}</td>
  <td><span class="pill s-{{ l.status }}">{{ l.status }}</span>
      {% if l.days_to_expiry is not none %}<div class=muted>{{ l.days_to_expiry }}d</div>{% endif %}</td>
  <td>{{ l.expires_at }}</td>
  <td class=muted>{{ (l.last_seen or '—')[:16].replace('T',' ') }}</td>
  <td>{{ l.last_truck_count if l.last_truck_count is not none else '—' }}</td>
  <td><div class=acts>
    {% if l.suspended %}
      <form method=post action="{{ url_for('admin_action', key=l.license_key, action='reactivate') }}"><button class=g type=submit>Reactivate</button></form>
    {% else %}
      <form method=post action="{{ url_for('admin_action', key=l.license_key, action='suspend') }}"><button class=r type=submit>Suspend</button></form>
    {% endif %}
    <form method=post action="{{ url_for('admin_action', key=l.license_key, action='extend1') }}"><button class=o type=submit>+1 mo</button></form>
    <form method=post action="{{ url_for('admin_action', key=l.license_key, action='extend12') }}"><button class=o type=submit>+1 yr</button></form>
  </div></td>
</tr>
{% else %}
<tr><td colspan=8 class=muted style="text-align:center;padding:2rem">No customers yet. Add your first above.</td></tr>
{% endfor %}
</table>
<p class=muted>Grace period: {{ grace }} days after expiry the customer stays writable with a "please renew" banner, then goes read-only (their data is never deleted). Today: {{ today }}.</p>
</div>
'''


if __name__ == '__main__':
    init_db()
    print(f'Munshi License Server on http://127.0.0.1:{PORT}  '
          f'(admin: /admin, verify: POST /verify)')
    if not ADMIN_PASSWORD:
        app.logger.warning('MUNSHI_ADMIN_PASSWORD not set — the web dashboard is locked until you set it.')
    if not ADMIN_TOKEN:
        app.logger.warning('MUNSHI_ADMIN_TOKEN not set — the JSON API (/provision) is disabled until you set it.')
    app.run(host='127.0.0.1', port=PORT, debug=False)
