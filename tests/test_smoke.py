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
from munshi.services import auth_service as _auth_service  # noqa: E402


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


# ── (4b) Login lockout survives a fresh DB connection (i.e. is NOT in-memory) ───
#
# Lockout used to be tracked in a plain in-memory dict, which reset on every
# app restart. It's now persisted in the `login_failures` table. This test
# guards that regression: after enough wrong passwords, the account must be
# locked, AND that lockout must be independently visible via a brand-new
# sqlite3 connection (proving it lives in the DB, not process memory).
def test_login_lockout_persists_across_connections(client):
    for _ in range(_auth_service._LOGIN_MAX_FAILURES):
        _login(client, "Owner", "wrong-password")

    # The account is now locked — the app's own lockout check agrees.
    assert appmod._login_lockout_remaining("Owner") > 0

    # A completely separate connection (simulating a fresh process after a
    # restart) sees the same failure rows — proof this isn't in-memory state.
    conn = _sqlite3.connect(appmod.DB_PATH)
    count = conn.execute(
        "SELECT COUNT(*) FROM login_failures WHERE username = ?", ("Owner",)
    ).fetchone()[0]
    conn.close()
    assert count >= 5

    # Correct password is still rejected while locked out.
    locked = _login(client, "Owner", "Owner")
    assert locked.status_code == 200  # re-renders login.html, no session
    with client.session_transaction() as sess:
        assert not sess.get("user")


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


# ── (F3) A bill number already taken by drifted data must NOT crash the save ───
#
# The `next_bill_number` counter can fall behind the real data — after loading
# demo/sample data, importing/restoring bills, manual DB edits, or a genuinely
# concurrent save. Before the fix, the next save hit `bills.bill_no UNIQUE` and
# blew up with an IntegrityError → 500. The save must instead skip the taken
# number, assign the next free one, and persist cleanly (no 500, no duplicate).
def test_bill_number_collision_does_not_500(client):
    _login_ready(client)

    # First real bill → JL-0001, counter advances to 2.
    r1 = _create_bill(client, "DRIFT CO", 1000)
    assert r1.status_code in (301, 302)

    # Simulate counter drift: inject the exact number the counter would hand out
    # next (JL-0002) directly, as demo/imported data would.
    conn = appmod.get_db()
    n = int(appmod.get_setting("next_bill_number") or 1)
    conn.execute(
        "INSERT INTO bills (bill_no, created_at) VALUES (?,?)",
        (f"JL-{n:04d}", appmod.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    # The next save used to 500 here. It must now redirect to a freshly-numbered
    # bill instead.
    r2 = _create_bill(client, "DRIFT CO", 2000)
    assert r2.status_code in (301, 302), (
        f"collision should be handled, not crash — got {r2.status_code}"
    )
    assert re.search(r"/bill/\d+", r2.headers.get("Location", ""))

    # No duplicate bill numbers exist.
    conn = appmod.get_db()
    rows = [row[0] for row in conn.execute("SELECT bill_no FROM bills").fetchall()]
    conn.close()
    assert len(rows) == len(set(rows)), f"duplicate bill numbers created: {rows}"


# ── (F1) Restore must be atomic and WAL-safe (no corruption / silent revert) ───
#
# The live DB runs in WAL mode. A naive restore (raw file-copy of the backup over
# bills.db) leaves the OLD database's -wal/-shm sidecars in place; SQLite then
# replays those stale frames onto the freshly restored file on the next open,
# silently corrupting or reverting a "successful" restore. The fixed restore
# copies the backup THROUGH the SQLite backup API into the live DB, so the
# restored state is exact, intact, and immediately usable.
import sqlite3 as _sqlite3  # noqa: E402


def test_restore_is_atomic_and_wal_safe(client):
    _login_ready(client)

    # State A: one bill. Snapshot it into a backup file (clean, backup API).
    _create_bill(client, "STATE-A CO", 1000)
    bkname = "bills-2020-01-01.db"
    bkpath = os.path.join(appmod.BACKUP_DIR, bkname)
    s1 = _sqlite3.connect(appmod.DB_PATH)
    s2 = _sqlite3.connect(bkpath)
    with s2:
        s1.backup(s2)
    s1.close()
    s2.close()

    # State B: add a second bill AND leave uncheckpointed frames in the WAL —
    # the exact precondition that used to corrupt the restored file.
    _create_bill(client, "STATE-B CO", 2000)
    w = _sqlite3.connect(appmod.DB_PATH)
    w.execute("PRAGMA wal_autocheckpoint=0")
    w.execute("INSERT INTO settings VALUES ('wal_marker','1')")
    w.commit()
    w.close()

    # Restore State A over the live DB via the real admin route.
    client.get("/restore")
    token = _csrf(client)
    resp = client.post("/restore", data={"filename": bkname, "csrf_token": token})
    assert resp.status_code in (301, 302)

    # Reopen and assert: intact, exactly State A, no State-B leakage, still usable.
    v = _sqlite3.connect(appmod.DB_PATH)
    integrity = v.execute("PRAGMA integrity_check").fetchone()[0]
    names = [r[0] for r in v.execute("SELECT recipient_name FROM bills ORDER BY id").fetchall()]
    leaked = v.execute("SELECT COUNT(*) FROM settings WHERE key='wal_marker'").fetchone()[0]
    v.close()
    assert integrity == "ok", "restored DB failed integrity check (corruption)"
    assert names == ["STATE-A CO"], f"restore did not produce the exact backup state: {names}"
    assert leaked == 0, "stale WAL frames from State B leaked into the restored DB"

    # The app keeps working on the restored DB.
    assert _create_bill(client, "STATE-A CO", 500).status_code in (301, 302)


# ── (G) Challan + invoice extraction: correct field-merge behavior ─────────────
#
# /challan/extract accepts two OPTIONAL photos — the transporter's own
# challan/LR and the consignor's separate commercial invoice (a different
# physical document). Real Gemini calls are mocked (deterministic, no
# network, no API cost) so these tests pin down the MERGE logic itself:
# challan-only, invoice-only, and both together — where the invoice's
# fields must win for invoice-specific data, but must NOT silently
# override consignor/consignee read off the challan photo.

import io  # noqa: E402


def _fake_challan_result(**overrides):
    data = {
        "lr_no": "9001", "challan_date": "2026-07-18",
        "consignor_name": "CHALLAN CONSIGNOR", "consignor_address": "Kanpur",
        "consignee_name": "CHALLAN CONSIGNEE", "consignee_address": "Pune",
        "from_city_state": "Kanpur, UP", "to_city_state": "Pune, MH",
        "invoice_no": "CHALLAN-INV-1", "invoice_date": "2026-07-01",
        "consignment_value": 1000, "gst_number": "CHALLANGSTIN",
        "no_of_articles": "10", "description": "from challan photo",
        "value_of_goods": 1000, "weight_kg": 500,
        "truck_no": "UP78AB1234", "driver_name": "Ramu", "driver_mobile": "9000000001",
        "confidence_per_field": {"lr_no": "low"},
    }
    data.update(overrides)
    return {"ok": True, "data": data, "error": None, "raw": "{}"}


def _fake_invoice_result(**overrides):
    data = {
        "invoice_no": "INVOICE-REAL-99", "invoice_date": "2026-07-05",
        "gst_number": "INVOICEGSTIN", "consignment_value": 5000,
        "no_of_articles": "20", "description": "from invoice photo",
        "value_of_goods": 5000,
        "consignor_name": "INVOICE CONSIGNOR", "consignor_address": "Delhi",
        "consignee_name": "INVOICE CONSIGNEE", "consignee_address": "Mumbai",
        "confidence_per_field": {"invoice_no": "medium"},
    }
    data.update(overrides)
    return {"ok": True, "data": data, "error": None, "raw": "{}"}


def _post_extract(client, monkeypatch, challan_result=None, invoice_result=None):
    if challan_result is not None:
        monkeypatch.setattr(appmod, "extract_challan_image", lambda path: challan_result)
    if invoice_result is not None:
        monkeypatch.setattr(appmod, "extract_invoice_image", lambda path: invoice_result)

    client.get("/challan/extract")
    token = _csrf(client)
    data = {"csrf_token": token}
    if challan_result is not None:
        data["challan_file"] = (io.BytesIO(b"fake-jpeg-bytes"), "challan.jpg")
    if invoice_result is not None:
        data["invoice_file"] = (io.BytesIO(b"fake-jpeg-bytes"), "invoice.jpg")
    return client.post("/challan/extract", data=data, content_type="multipart/form-data",
                        follow_redirects=False)


def test_challan_only_extraction(client, monkeypatch):
    """Only a challan photo — works exactly as before this feature existed."""
    _login_ready(client)
    resp = _post_extract(client, monkeypatch, challan_result=_fake_challan_result())
    assert resp.status_code in (301, 302)
    cid = int(re.search(r"/challan/(\d+)", resp.headers["Location"]).group(1))
    row = appmod.get_db().execute("SELECT * FROM challans WHERE id=?", (cid,)).fetchone()
    assert row["consignor_name"] == "CHALLAN CONSIGNOR"
    assert row["invoice_no"] == "CHALLAN-INV-1"  # challan photo's own guess, no invoice photo given
    assert row["source_image"] is not None
    assert row["invoice_source_image"] is None


def test_invoice_only_extraction(client, monkeypatch):
    """Only an invoice photo — fills invoice fields + consignor/consignee
    (no challan photo to read those from), leaves challan-specific fields
    (truck/driver) blank."""
    _login_ready(client)
    resp = _post_extract(client, monkeypatch, invoice_result=_fake_invoice_result())
    assert resp.status_code in (301, 302)
    cid = int(re.search(r"/challan/(\d+)", resp.headers["Location"]).group(1))
    row = appmod.get_db().execute("SELECT * FROM challans WHERE id=?", (cid,)).fetchone()
    assert row["invoice_no"] == "INVOICE-REAL-99"
    assert row["consignor_name"] == "INVOICE CONSIGNOR"  # invoice-only mode: OK to fill this in
    assert row["truck_no"] == ""  # nothing read this — must stay blank, not crash
    assert row["source_image"] is None
    assert row["invoice_source_image"] is not None


def test_challan_and_invoice_together_merge_correctly(client, monkeypatch):
    """Both photos at once: invoice-specific fields (invoice_no/value/etc.)
    must come from the INVOICE photo (more authoritative), but consignor/
    consignee must stay from the CHALLAN photo — the invoice must not
    silently overwrite what the challan photo already showed."""
    _login_ready(client)
    resp = _post_extract(
        client, monkeypatch,
        challan_result=_fake_challan_result(),
        invoice_result=_fake_invoice_result(),
    )
    assert resp.status_code in (301, 302)
    cid = int(re.search(r"/challan/(\d+)", resp.headers["Location"]).group(1))
    row = appmod.get_db().execute("SELECT * FROM challans WHERE id=?", (cid,)).fetchone()

    # Invoice-specific fields: invoice photo wins.
    assert row["invoice_no"] == "INVOICE-REAL-99"
    assert row["gst_number"] == "INVOICEGSTIN"
    assert row["value_of_goods"] == 5000

    # Challan-specific fields: only the challan photo could have supplied these.
    assert row["truck_no"] == "UP78AB1234"
    assert row["driver_name"] == "Ramu"

    # Consignor/consignee: must stay from the CHALLAN photo, not get
    # silently overwritten by the invoice photo's own guess.
    assert row["consignor_name"] == "CHALLAN CONSIGNOR"
    assert row["consignee_name"] == "CHALLAN CONSIGNEE"

    # Both photos were saved, both raw extractions kept.
    assert row["source_image"] is not None
    assert row["invoice_source_image"] is not None


def test_extract_requires_at_least_one_photo(client):
    """POSTing with neither file must not crash — it should just bounce back
    to the upload page with a flash message."""
    _login_ready(client)
    client.get("/challan/extract")
    token = _csrf(client)
    resp = client.post("/challan/extract", data={"csrf_token": token},
                        content_type="multipart/form-data", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/challan/extract" in resp.headers.get("Location", "")


# ── (H) Ledger POD-time settlement adjustments: correct money math ─────────────
#
# ledger_pod() lets shortage/leakage/breakage/unloading/detention/toll_tax/
# excess_km be entered when marking POD. These feed directly into what's owed
# to the transporter (_ledger_balance() / _transporter_charges_net()) — a
# formula mismatch here is a real money bug, not just a UI bug. Convention:
# shortage/leakage/breakage/unloading DEDUCT from freight; detention/
# toll_tax/excess_km ADD to it.

def _create_transporter(client, name):
    client.get("/masters")
    token = _csrf(client)
    client.post("/masters/transporter/add",
                 data={"csrf_token": token, "name": name, "mobile": "",
                       "bank_details": "", "notes": ""},
                 follow_redirects=False)
    row = appmod.get_db().execute(
        "SELECT id FROM transporters WHERE name=?", (name,)).fetchone()
    return row["id"]


def _create_ledger_entry(transporter_id, freight, advance_cash=0, advance_account=0, diesel=0):
    conn = appmod.get_db()
    conn.execute(
        """INSERT INTO ledger_entries
           (entry_date, gr_no, vehicle_no, freight, advance_cash, advance_account, diesel,
            transporter_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("2026-07-18", f"GR-{transporter_id}-TEST", "UP78TEST01", freight, advance_cash,
         advance_account, diesel, transporter_id, appmod.datetime.now().isoformat()),
    )
    conn.commit()
    le_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return le_id


def test_pod_shortage_deducts_from_transporter_balance(client):
    _login_ready(client)
    tid = _create_transporter(client, "Shortage Test Transport")
    le_id = _create_ledger_entry(tid, freight=10000)
    assert appmod.get_party_balance("transporter", tid) == 10000

    client.get(f"/ledger/{le_id}")
    token = _csrf(client)
    resp = client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-19",
        "shortage": "1500",
    }, content_type="multipart/form-data", follow_redirects=False)
    assert resp.status_code in (301, 302)

    balance = appmod.get_party_balance("transporter", tid)
    assert balance == 8500, f"shortage should deduct from balance, got {balance}"


def test_pod_detention_toll_excess_km_add_to_transporter_balance(client):
    _login_ready(client)
    tid = _create_transporter(client, "Detention Test Transport")
    le_id = _create_ledger_entry(tid, freight=10000)

    client.get(f"/ledger/{le_id}")
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-19",
        "detention": "800", "toll_tax": "200", "excess_km": "500",
    }, content_type="multipart/form-data", follow_redirects=False)

    balance = appmod.get_party_balance("transporter", tid)
    assert balance == 11500, f"detention/toll/excess_km should ADD to balance, got {balance}"


def test_pod_quick_mark_does_not_reset_existing_adjustments(client):
    """A quick one-tap 'Mark POD' (no adjustment fields in the POST) must not
    silently wipe out adjustments already entered via the full modal."""
    _login_ready(client)
    tid = _create_transporter(client, "Quicktap Test Transport")
    le_id = _create_ledger_entry(tid, freight=10000)

    client.get(f"/ledger/{le_id}")
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-19",
        "shortage": "2000",
    }, content_type="multipart/form-data", follow_redirects=False)
    assert appmod.get_party_balance("transporter", tid) == 8000

    # Quick re-tap: only pod_received/pod_date, no adjustment fields at all.
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-20",
    }, content_type="multipart/form-data", follow_redirects=False)

    balance = appmod.get_party_balance("transporter", tid)
    assert balance == 8000, f"quick re-tap must not reset the earlier shortage, got {balance}"


def test_pod_adjustments_sync_into_already_paid_trip(client):
    """If a trip is already marked paid (auto-payment row exists), editing
    adjustments afterward must update that payment row too, or the
    transporter's balance would silently disagree with what Payments shows."""
    _login_ready(client)
    tid = _create_transporter(client, "Resync Test Transport")
    le_id = _create_ledger_entry(tid, freight=10000)

    # Mark paid first, with no adjustments yet -- auto payment = 10000.
    client.get(f"/ledger/{le_id}")
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/paid", data={
        "csrf_token": token, "paid": "1", "paid_date": "2026-07-19", "paid_mode": "Cash",
    }, follow_redirects=False)
    assert appmod.get_party_balance("transporter", tid) == 0

    # Now record a shortage after the fact.
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-19",
        "shortage": "1000",
    }, content_type="multipart/form-data", follow_redirects=False)

    # The auto-payment mirror must have followed the adjustment, so the
    # balance still nets to zero (paid the net owed, not stale at 10000).
    balance = appmod.get_party_balance("transporter", tid)
    assert balance == 0, f"auto-payment should re-sync with the new net after POD edit, got {balance}"


def test_pod_delivery_date_saved_and_not_reset_by_quick_tap(client):
    """delivery_date (manually entered, distinct from pod_date) must persist,
    and — like the settlement adjustments — must not be wiped by a quick
    one-tap POD action that doesn't submit it."""
    _login_ready(client)
    tid = _create_transporter(client, "DeliveryDate Test Transport")
    le_id = _create_ledger_entry(tid, freight=5000)

    client.get(f"/ledger/{le_id}")
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-19",
        "delivery_date": "2026-07-17",
    }, content_type="multipart/form-data", follow_redirects=False)

    row = appmod.get_db().execute(
        "SELECT delivery_date FROM ledger_entries WHERE id=?", (le_id,)).fetchone()
    assert row["delivery_date"] == "2026-07-17"

    # Quick re-tap without delivery_date in the payload.
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-20",
    }, content_type="multipart/form-data", follow_redirects=False)

    row = appmod.get_db().execute(
        "SELECT delivery_date FROM ledger_entries WHERE id=?", (le_id,)).fetchone()
    assert row["delivery_date"] == "2026-07-17", "quick re-tap must not reset delivery_date"


# ── (I) Freight rate-list Excel import: header-name matching, not fixed columns ─
#
# import_rate_list_from_xlsx() used to require the exact Book1.xlsx column
# order. It now recognises columns by header keyword, in any order/sheet, and
# upserts on (customer_name, location) so re-uploading updated rates replaces
# the existing row instead of duplicating it.

def _xlsx_bytes(rows):
    import io as _io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def test_rate_list_import_recognizes_reordered_nonstandard_headers(client, tmp_path):
    """A rate list whose columns are in a different order, with different
    wording, and missing some optional columns entirely (not the Book1.xlsx
    layout at all) must still import correctly by matching header keywords."""
    _login_ready(client)
    xlsx = _xlsx_bytes([
        ["Code", "Party Name", "Destination", "Rate OWY", "Rate TWY"],
        ["C001", "Test Customer", "Kanpur", 45000, 90000],
    ])
    path = tmp_path / "rates.xlsx"
    path.write_bytes(xlsx)
    count, msg = appmod.import_rate_list_from_xlsx(str(path))
    assert count == 1, msg
    row = appmod.get_db().execute(
        "SELECT * FROM freight_rates WHERE customer_name='TEST CUSTOMER'").fetchone()
    assert row is not None
    assert row["party_code"] == "C001"
    assert row["location"] == "KANPUR"
    assert row["lp_owy"] == 45000
    assert row["lp_twy"] == 90000
    assert row["dist_owy_km"] is None  # column wasn't present in this file — left blank, no crash


def test_rate_list_reupload_updates_existing_row_not_duplicate(client, tmp_path):
    """The user's core question: edit a rate in Excel, re-upload the whole
    file, and the existing customer+location row must be UPDATED in place —
    not duplicated — because of the ON CONFLICT(customer_name, location) upsert."""
    _login_ready(client)
    first = tmp_path / "rates1.xlsx"
    first.write_bytes(_xlsx_bytes([
        ["Customer Name", "Location", "LP OWY", "LP TWY"],
        ["ABC Industries", "Mumbai", 45000, 90000],
    ]))
    count1, _ = appmod.import_rate_list_from_xlsx(str(first))
    assert count1 == 1

    second = tmp_path / "rates2.xlsx"
    second.write_bytes(_xlsx_bytes([
        ["Customer Name", "Location", "LP OWY", "LP TWY"],
        ["ABC Industries", "Mumbai", 48000, 95000],  # same customer+location, new rate
    ]))
    count2, _ = appmod.import_rate_list_from_xlsx(str(second))
    assert count2 == 1

    rows = appmod.get_db().execute(
        "SELECT * FROM freight_rates WHERE customer_name='ABC INDUSTRIES'").fetchall()
    assert len(rows) == 1, "re-upload must update the existing row, not create a duplicate"
    assert rows[0]["lp_owy"] == 48000
    assert rows[0]["lp_twy"] == 95000


def test_rate_list_import_handles_two_row_merged_headers(client, tmp_path):
    """Real-world rate lists often use a merged two-row header: a group label
    ('LP-Truck' / 'Trolla-Truck' / 'Distence (Sachindi)') on one row, with the
    bare direction ('OWY'/'TWY') on the row directly below it (the reported
    bug: only Customer/Code/Location came through, the 6 rate/distance
    columns were blank because 'OWY'/'TWY' alone don't say which group they
    belong to without the merged label above them)."""
    _login_ready(client)
    xlsx = _xlsx_bytes([
        ["Customer Name", "Party Code", "Location", "Distence (Sachindi)", None, "LP-Truck", None, "Trolla-Truck", None],
        [None, None, None, "Dis TWY", "Dis OWY", "OWY", "TWY", "OWY", "TWY"],
        ["Test Customer", "C001", "Kanpur", 70, 35, 4163, 4163, 5780, 5780],
    ])
    path = tmp_path / "merged.xlsx"
    path.write_bytes(xlsx)
    count, msg = appmod.import_rate_list_from_xlsx(str(path))
    assert count == 1, msg
    row = appmod.get_db().execute(
        "SELECT * FROM freight_rates WHERE customer_name='TEST CUSTOMER'").fetchone()
    assert row is not None
    assert row["dist_twy_km"] == 70
    assert row["dist_owy_km"] == 35
    assert row["lp_owy"] == 4163
    assert row["lp_twy"] == 4163
    assert row["trolla_owy"] == 5780
    assert row["trolla_twy"] == 5780


def test_rate_list_import_handles_group_label_above_field_row(client, tmp_path):
    """The ACTUAL real-world file reported by the user: the group label row
    ('LP-Truck'/'Trolla-Truck'/'Distence (Sachindi)') sits ABOVE the row that
    has 'Customer'/'Location'/'OWY'/'TWY' — the opposite direction from the
    other merged-header test — with two unrelated title/subtitle rows above
    that ('Rate List of 2024 Sachendi', 'Diesel Rate @ 90 (2023)'). Only
    Customer/Code/Location/distances came through before this fix; the 4
    rate columns (bare 'OWY'/'TWY' with no group label on their own row)
    stayed blank because the importer only ever looked at the row BELOW."""
    _login_ready(client)
    xlsx = _xlsx_bytes([
        [None, None, None, None, None, "Rate List of 2024 Sachendi", None, None, None],
        [None, None, None, None, None, "Diesel Rate @ 90 (2023)", None, None, None],
        [None, None, None, "Distence (Sachindi)", None, "LP-Truck", None, "Trolla-Truck", None],
        ["Customer", "Code", "Location", "Dis TWY", "Dis OWY", "OWY", "TWY", "OWY", "TWY"],
        ["K-Kanpur Traders", "158192", "K-Kanpur", 70, 35, 4163, 4163, 5780, 5780],
    ])
    path = tmp_path / "real_layout.xlsx"
    path.write_bytes(xlsx)
    count, msg = appmod.import_rate_list_from_xlsx(str(path))
    assert count == 1, msg
    row = appmod.get_db().execute(
        "SELECT * FROM freight_rates WHERE customer_name='K-KANPUR TRADERS'").fetchone()
    assert row is not None
    assert row["dist_twy_km"] == 70
    assert row["dist_owy_km"] == 35
    assert row["lp_owy"] == 4163
    assert row["lp_twy"] == 4163
    assert row["trolla_owy"] == 5780
    assert row["trolla_twy"] == 5780


def test_rate_list_import_requires_customer_name_column(client, tmp_path):
    """A file with no recognisable customer-name header must fail clearly,
    not silently import garbage."""
    _login_ready(client)
    path = tmp_path / "bad.xlsx"
    path.write_bytes(_xlsx_bytes([
        ["Something", "Else"],
        ["1", "2"],
    ]))
    count, msg = appmod.import_rate_list_from_xlsx(str(path))
    assert count == 0
    assert "customer" in msg.lower() or "Customer" in msg


# ── (J) Drive restore-on-boot (free-tier hosted persistence) ───────────────
#
# On hosts that wipe the disk on redeploy (e.g. Render free tier), a fresh
# container has no bills.db. _restore_latest_backup_from_drive() tries to
# pull the latest Drive backup down before the normal blank-seed bootstrap
# runs. This must NEVER be able to block/crash startup — these tests lock in
# the safe-fallback behavior for the common cases (not configured, API
# failure) and confirm the wiring correctly skips the blank seed when a
# restore succeeds.

def test_drive_restore_noop_when_bootstrap_token_not_set(monkeypatch):
    """The overwhelmingly common case (free-hosting restore not configured,
    or a normal desktop install): must return False immediately without
    attempting any network call."""
    monkeypatch.delenv("MUNSHI_DRIVE_BOOTSTRAP_REFRESH_TOKEN", raising=False)
    assert appmod._restore_latest_backup_from_drive() is False


def test_drive_restore_noop_when_oauth_not_configured(monkeypatch):
    """Token set but no OAuth client configured server-side (drive_configured
    is False) — still must safely no-op, not attempt a call that will fail."""
    monkeypatch.setenv("MUNSHI_DRIVE_BOOTSTRAP_REFRESH_TOKEN", "fake-token")
    monkeypatch.setattr(appmod, "GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(appmod, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    assert appmod._restore_latest_backup_from_drive() is False


def test_drive_restore_swallows_api_errors(monkeypatch):
    """Token configured but the Google API call blows up (revoked token,
    network error, etc.) — must be swallowed, never raised, so a bad/stale
    bootstrap token can't take down startup."""
    monkeypatch.setenv("MUNSHI_DRIVE_BOOTSTRAP_REFRESH_TOKEN", "fake-token")
    monkeypatch.setattr(appmod, "GOOGLE_OAUTH_CLIENT_ID", "fake-id")
    monkeypatch.setattr(appmod, "GOOGLE_OAUTH_CLIENT_SECRET", "fake-secret")

    class _ExplodingCredentials:
        def __init__(self, *a, **kw):
            pass

        def refresh(self, *a, **kw):
            raise RuntimeError("simulated: invalid_grant")

    import google.oauth2.credentials
    monkeypatch.setattr(google.oauth2.credentials, "Credentials", _ExplodingCredentials)

    # Must not raise.
    assert appmod._restore_latest_backup_from_drive() is False


def test_bootstrap_from_seed_skips_seed_copy_when_drive_restore_succeeds(tmp_path, monkeypatch):
    """Wiring check: if _restore_latest_backup_from_drive() reports success
    (a real backup was restored), _bootstrap_from_seed_if_missing() must NOT
    also overwrite it with the blank seed."""
    fresh_db = tmp_path / "fresh_bills.db"
    appmod.DB_PATH = str(fresh_db)
    assert not fresh_db.exists()

    def _fake_restore():
        # Simulate a successful Drive restore by writing a real sqlite file.
        conn = appmod.sqlite3.connect(str(fresh_db))
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings VALUES ('restored_from_drive', '1')")
        conn.commit()
        conn.close()
        return True

    monkeypatch.setattr(appmod, "_restore_latest_backup_from_drive", _fake_restore)
    appmod._bootstrap_from_seed_if_missing()

    conn = appmod.sqlite3.connect(str(fresh_db))
    row = conn.execute("SELECT value FROM settings WHERE key='restored_from_drive'").fetchone()
    conn.close()
    assert row is not None and row[0] == '1', \
        "blank seed must not have overwritten the Drive-restored database"


# ── (K) Freight/advances editable via a separate "Edit Amounts" popup ──────
#
# Reported: editing freight at POD time meant the only path was the Mark POD
# popup, which also marks the trip as delivered as a side effect - not
# appropriate for just correcting a number before delivery. Money fields
# (freight, advance_cash, advance_account, diesel) now live in their own
# /ledger/<id>/amounts endpoint, entirely separate from ledger_pod(), which
# no longer touches freight at all.

def test_ledger_pod_no_longer_touches_freight(client):
    """ledger_pod() must ignore any 'freight' field entirely now - editing
    it moved to its own endpoint."""
    _login_ready(client)
    tid = _create_transporter(client, "POD No Freight Test Transport")
    le_id = _create_ledger_entry(tid, freight=10000)
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/pod", data={
        "csrf_token": token, "pod_received": "1", "pod_date": "2026-07-19",
        "freight": "999999",
    }, content_type="multipart/form-data", follow_redirects=False)
    row = appmod.get_db().execute(
        "SELECT freight FROM ledger_entries WHERE id=?", (le_id,)).fetchone()
    assert row["freight"] == 10000, "ledger_pod() must not change freight anymore"


def test_ledger_amounts_updates_freight_and_advances(client):
    _login_ready(client)
    tid = _create_transporter(client, "Amounts Update Test Transport")
    le_id = _create_ledger_entry(tid, freight=10000, advance_cash=1000, advance_account=500, diesel=2000)
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/amounts", data={
        "csrf_token": token, "freight": "12500", "advance_cash": "1500",
        "advance_account": "500", "diesel": "2000",
    }, follow_redirects=False)
    row = appmod.get_db().execute(
        "SELECT freight, advance_cash, advance_account, diesel FROM ledger_entries WHERE id=?",
        (le_id,)).fetchone()
    assert row["freight"] == 12500
    assert row["advance_cash"] == 1500
    # 12500 freight - 1500 adv cash - 500 adv a/c - 2000 diesel = 8500
    assert appmod.get_party_balance("transporter", tid) == 8500


def test_ledger_amounts_blank_field_keeps_existing_value(client):
    """A blank/unparseable field falls back to the existing value instead of
    zeroing it out — the popup pre-fills every field, so this only matters
    if a field gets cleared unintentionally."""
    _login_ready(client)
    tid = _create_transporter(client, "Amounts Blank Test Transport")
    le_id = _create_ledger_entry(tid, freight=8000, advance_cash=500)
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/amounts", data={
        "csrf_token": token, "freight": "", "advance_cash": "700",
    }, follow_redirects=False)
    row = appmod.get_db().execute(
        "SELECT freight, advance_cash FROM ledger_entries WHERE id=?", (le_id,)).fetchone()
    assert row["freight"] == 8000, "blank freight submission must not zero it out"
    assert row["advance_cash"] == 700


def test_ledger_amounts_syncs_already_paid_trip(client):
    """Same as ledger_pod()'s payment-mirror sync: the auto-payment mirror
    always records whatever the CURRENT net charge is, so a fully-paid
    trip's outstanding balance stays 0 even after the freight is corrected
    (the recorded rupee amount moves; the debt does not silently reappear).
    Confirm the mirror actually re-synced (not just coincidentally still 0)
    by checking the underlying auto-payment row's amount directly."""
    _login_ready(client)
    tid = _create_transporter(client, "Amounts Paid Sync Test Transport")
    le_id = _create_ledger_entry(tid, freight=10000)
    token = _csrf(client)
    client.post(f"/ledger/{le_id}/paid", data={
        "csrf_token": token, "paid": "1", "paid_date": "2026-07-19", "paid_mode": "Cash",
    }, follow_redirects=False)
    assert appmod.get_party_balance("transporter", tid) == 0

    token = _csrf(client)
    client.post(f"/ledger/{le_id}/amounts", data={
        "csrf_token": token, "freight": "13000",
    }, follow_redirects=False)
    assert appmod.get_party_balance("transporter", tid) == 0, \
        "a fully-paid trip must stay fully paid after correcting freight"
    auto_row = appmod.get_db().execute(
        "SELECT amount FROM payments WHERE reference=?", (f'auto-paid:ledger:{le_id}',)).fetchone()
    assert auto_row["amount"] == 13000, \
        "the auto-payment mirror must follow the corrected freight, not stay at the old amount"
