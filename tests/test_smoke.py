"""
Smoke tests for the Munshi / Jainpur Logistic Flask app.

Goal: a future code change can't SILENTLY break the money math or the core
happy-path (boot, login, create a bill, record a client payment).

These tests are deliberately self-contained:

  * They drive the app through Flask's built-in test client
    (`app.app.test_client()`) — no real server, no real port, no network.
  * Every test runs against a FRESH throwaway copy of the database in a temp
    directory. The real `bills.db`, `backups/`, and `uploads/` next to the app
    are never touched. We do this by importing the app module and then
    re-pointing its module-level `DB_PATH`, `BACKUP_DIR`, and `UPLOAD_DIR` at a
    temp dir BEFORE calling `init_db()`. (The app resolves those paths from
    module globals at call time, so re-pointing them is enough — see app.py
    `get_db()` / `DB_PATH`.)

Run:  python3 -m pytest tests/ -q      (see tests/README.md)
"""

import os
import re
import sys

import pytest

# ── Locate the app package (the directory ABOVE this tests/ folder) ────────────
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Neutralise environment BEFORE importing app.py so importing it can't:
#   * write a per-install .flask_secret file into the real project dir
#   * turn on license lockout (which would block the POST tests)
#   * phone home to a license server
os.environ["FLASK_SECRET_KEY"] = "smoke-test-secret-key-that-is-well-over-32-characters-long"
os.environ.pop("MUNSHI_REQUIRE_LICENSE", None)
os.environ.pop("LICENSE_SERVER_URL", None)

import app as appmod  # noqa: E402  (import must follow the env setup above)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path):
    """A logged-out Flask test client backed by a fresh temp DB.

    Each test gets its own bills.db (bootstrapped from data/seed.db if present,
    otherwise created empty and seeded) so tests never interfere with each
    other or with the developer's real data.
    """
    db_dir = tmp_path / "munshi"
    db_dir.mkdir(parents=True, exist_ok=True)

    # Re-point ALL filesystem state at the temp dir, then build the DB.
    appmod.DB_PATH = str(db_dir / "bills.db")
    appmod.BACKUP_DIR = str(db_dir / "backups")
    appmod.UPLOAD_DIR = str(db_dir / "uploads")
    os.makedirs(appmod.BACKUP_DIR, exist_ok=True)
    os.makedirs(appmod.UPLOAD_DIR, exist_ok=True)

    appmod.init_db()

    # The shipped seed is now BLANK (no users) with a first-run setup wizard.
    # Recreate the configured-install condition these tests expect: an admin
    # Owner (password "Owner", forced first-login change) + setup marked
    # complete + a supplier name — so login/bill/payment flows run instead of
    # being redirected to the wizard.
    _conn = appmod.get_db()
    _conn.execute(
        "INSERT OR REPLACE INTO users (username, password_hash, full_name, role, "
        "is_active, must_change_password, created_at) VALUES (?,?,?,?,1,1,?)",
        ("Owner", appmod._hash_password("Owner"), "Owner", "admin",
         appmod.datetime.now().isoformat()))
    _conn.execute("INSERT OR REPLACE INTO settings VALUES ('setup_complete','1')")
    _conn.execute("INSERT OR REPLACE INTO settings VALUES ('supplier_name','TEST TRANSPORT CO')")
    _conn.commit()
    _conn.close()

    appmod.app.config.update(TESTING=True)
    return appmod.app.test_client()


# ── Small helpers ──────────────────────────────────────────────────────────────

def _csrf(client):
    """Read the CSRF token the app seeded into the session.

    The app sets `session['csrf_token']` on every request (see `_seed_csrf_token`
    in app.py), so any prior GET is enough to populate it.
    """
    with client.session_transaction() as sess:
        return sess.get("csrf_token", "")


def _login(client, username, password):
    """POST the login form with a valid CSRF token. Returns the response."""
    client.get("/login")  # seeds csrf_token into the session
    token = _csrf(client)
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def _login_ready(client, new_password="Owner1234"):
    """Log in as the seeded Owner AND clear the forced first-login password
    change, leaving the client ready to hit normal pages.

    Returns the password now in effect for Owner.
    """
    _login(client, "Owner", "Owner")
    client.get("/change-password")
    token = _csrf(client)
    client.post(
        "/change-password",
        data={
            "old_password": "Owner",
            "new_password": new_password,
            "confirm_password": new_password,
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    return new_password


def _create_bill(client, recipient_name, value_of_supply):
    """Create a reverse-charge bill (so total_amount == taxable value, no tax
    math to reconcile) for `recipient_name`. Returns the /bill/<id> location.
    """
    client.get("/bill/new")
    token = _csrf(client)
    resp = client.post(
        "/bill/new",
        data={
            "csrf_token": token,
            "delivery_count": "1",
            "bill_date": "2026-07-15",
            "recipient_name": recipient_name,
            "recipient_address": "Kanpur Dehat",
            "recipient_gstin": "",
            "state_code": "09",
            "trip_type": "One Way",
            "vehicle_no": "UP78TEST01",
            "delivery_month_select": "JUL",
            "reverse_charge": "on",
            "d_value_of_supply_0": str(value_of_supply),
        },
        follow_redirects=False,
    )
    return resp


def _dashboard_client_outstanding(recipient_name):
    """The DASHBOARD KPI source of truth for client outstanding.

    Mirrors the `client_outstanding` KPI in the /dashboard route. After the
    Phase-1 single-source-of-truth fix, that KPI is computed the SAME way as
    the payments hub — via `get_party_balance('client', ...)` (charges minus
    rows in the `payments` table) — instead of the old per-bill `client_paid`
    flag. Keeping this helper in sync with the fixed dashboard is exactly what
    the README anticipated when it said the fix would make this test pass.
    (Restricted here to one client so we can read this client's movement.)
    """
    return float(appmod.get_party_balance("client", recipient_name))


def _hub_client_balance(recipient_name):
    """The PAYMENTS-HUB source of truth for the same client.

    This is exactly what the payments hub uses (via `list_clients_with_balance`
    → `get_party_balance('client', ...)`): total billed minus rows in the
    `payments` table.
    """
    return float(appmod.get_party_balance("client", recipient_name))


# ── (1) App boots and /health returns ok ───────────────────────────────────────

def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None, "/health should return JSON"
    assert data.get("ok") is True
    # DB check should be reachable and report the (empty) bills table.
    assert data["checks"]["db"]["ok"] is True


def test_home_requires_login(client):
    """A protected page redirects an anonymous visitor to /login."""
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers.get("Location", "")


# ── (2) Login + forced first-login password change ─────────────────────────────

def test_login_and_forced_password_change(client):
    # Wrong password is rejected (stays on the login page, no session user).
    bad = _login(client, "Owner", "wrong-password")
    assert bad.status_code == 200  # re-renders login.html, not a redirect
    with client.session_transaction() as sess:
        assert not sess.get("user")

    # Correct seeded credentials log in, but the account is flagged
    # must_change_password, so any normal page bounces to /change-password.
    ok = _login(client, "Owner", "Owner")
    assert ok.status_code in (301, 302)
    with client.session_transaction() as sess:
        assert sess.get("user") == "Owner"
        assert sess.get("must_change_password") is True

    forced = client.get("/dashboard", follow_redirects=False)
    assert forced.status_code in (301, 302)
    assert "/change-password" in forced.headers.get("Location", "")

    # Complete the change; the flag clears and normal pages load.
    client.get("/change-password")
    token = _csrf(client)
    changed = client.post(
        "/change-password",
        data={
            "old_password": "Owner",
            "new_password": "Owner1234",
            "confirm_password": "Owner1234",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert changed.status_code in (301, 302)
    with client.session_transaction() as sess:
        assert sess.get("must_change_password") is False

    # The dashboard now loads directly.
    assert client.get("/dashboard").status_code == 200


# ── (3) Creating a bill persists and the bill view renders 200 ─────────────────

def test_create_bill_persists_and_renders(client):
    _login_ready(client)

    before = _hub_client_balance("ACME TRADERS")  # 0 for a brand-new client
    resp = _create_bill(client, "ACME TRADERS", 12345)
    assert resp.status_code in (301, 302), "POST /bill/new should redirect to the new bill"
    location = resp.headers.get("Location", "")
    assert re.search(r"/bill/\d+", location), f"unexpected redirect: {location}"

    # The bill view renders.
    view = client.get(location)
    assert view.status_code == 200

    # It actually persisted with the right total (reverse-charge => total == taxable).
    after = _hub_client_balance("ACME TRADERS")
    assert after - before == pytest.approx(12345.0, abs=0.5), (
        "billed total should show up as the client's charge"
    )


# ── (4) Recording a client payment must move BOTH balance sources the same way ─
#
# This is the known "split-brain" payment bug guard.
#
#   * The dashboard KPI computes client outstanding from the per-bill
#     `client_paid` flag (bills table).
#   * The payments hub computes it from the `payments` table
#     (get_party_balance).
#
# Recording a payment must move the client's outstanding by the same amount on
# BOTH the dashboard KPI source and the payments-hub source. After the Phase-1
# single-source-of-truth fix, both read get_party_balance (charges minus the
# payments table), so this is now a hard regression guard (previously xfail).
def test_client_payment_moves_both_sources_same_direction(client):
    name = "SPLITBRAIN CLIENT"
    _login_ready(client)
    _create_bill(client, name, 10000)

    dash_before = _dashboard_client_outstanding(name)
    hub_before = _hub_client_balance(name)
    assert dash_before == pytest.approx(hub_before, abs=0.5), (
        "before any payment the two sources should already agree"
    )

    # Record a client payment through the payments hub.
    client.get("/payments/add")  # seeds csrf (any GET would do)
    token = _csrf(client)
    pay = client.post(
        "/payments/add",
        data={
            "csrf_token": token,
            "party_type": "client",
            "party_key": name,
            "amount": "4000",
            "payment_date": "2026-07-15",
            "mode": "UPI",
        },
        follow_redirects=False,
    )
    assert pay.status_code in (301, 302)

    dash_after = _dashboard_client_outstanding(name)
    hub_after = _hub_client_balance(name)

    dash_delta = dash_before - dash_after  # how much outstanding dropped
    hub_delta = hub_before - hub_after

    # Both sources must recognise the payment (drop by the same amount).
    assert hub_delta == pytest.approx(4000.0, abs=0.5)
    assert dash_delta == pytest.approx(4000.0, abs=0.5)
    assert dash_delta == pytest.approx(hub_delta, abs=0.5)


# ── (5) Money-math helpers: amount-in-words + GST split ─────────────────────────

def test_amount_in_words_inr():
    assert appmod.amount_in_words_inr(0) == "Rupees Zero Only"
    # Indian numbering (Lakh/Thousand) — matches the docstring example.
    assert appmod.amount_in_words_inr(147997) == (
        "Rupees One Lakh Forty Seven Thousand Nine Hundred Ninety Seven Only"
    )
    assert appmod.amount_in_words_inr(100) == "Rupees One Hundred Only"
    # Never raises on junk input.
    assert appmod.amount_in_words_inr(None) == "Rupees Zero Only"


def test_gst_split_reverse_charge_is_zero_tax():
    out = appmod.compute_gst_split(10000, 5, "09", "09", reverse_charge=True)
    assert out["total_tax"] == 0
    assert out["grand_total"] == 10000


def test_gst_split_same_state_is_cgst_sgst():
    out = appmod.compute_gst_split(10000, 5, "09", "09", reverse_charge=False)
    # 5% split evenly: 2.5% CGST + 2.5% SGST = 250 + 250.
    assert out["cgst_amount"] == 250
    assert out["sgst_amount"] == 250
    assert out["igst_amount"] == 0
    assert out["total_tax"] == 500
    assert out["grand_total"] == 10500


def test_gst_split_inter_state_is_igst():
    out = appmod.compute_gst_split(10000, 5, "09", "27", reverse_charge=False)
    # Different states => single IGST line at the full rate.
    assert out["igst_amount"] == 500
    assert out["cgst_amount"] == 0
    assert out["sgst_amount"] == 0
    assert out["total_tax"] == 500
    assert out["grand_total"] == 10500
