#!/usr/bin/env python3
"""
make_seeds.py — generate shippable seed databases for Munshi (Jainpur Logistic app).

WHY THIS EXISTS
---------------
The app currently ships `data/seed.db`, which is a clone of the founder's REAL
business: real GSTIN, real customers, real freight rates, and 4 real user logins
(Owner / Ankur / Amit / Neeraj). That file must NEVER ship to other customers.

This tool produces two clean replacements that CAN ship:

  1) data/seed_blank.db  — schema + generic defaults, everything identity-related
                           blank, no users, no bills/ledger/rates. The app's setup
                           wizard creates the owner account on first run.
                           settings: setup_complete='0'.

  2) data/seed_demo.db   — same schema, pre-filled with an obviously-fake demo
                           transporter ("DEMO ROADLINES (SAMPLE)") so a prospect
                           can click around a populated app. One login: Demo / Demo.
                           settings: setup_complete='1', is_demo='1'.

HOW IT WORKS
------------
- It does NOT import app.py (to avoid triggering the real app's bootstrap/init).
- It reads only the SCHEMA (CREATE TABLE / CREATE INDEX statements) from the
  existing data/seed.db via sqlite_master — never any of its rows. SQLite stores
  the *final* CREATE TABLE text (with ALTER-added columns folded in) in
  sqlite_master, so this reproduces the app's exact schema without re-typing it.
- It then inserts only the rows we explicitly want.
- The password hash for the Demo user is produced with the SAME format as app.py's
  _hash_password: PBKDF2-HMAC-SHA256, 16-byte salt, 200000 iterations,
  base64(salt + hash).

It will NOT touch data/seed.db.

Usage:  python3 tools/make_seeds.py
"""

import os
import sqlite3
import base64
import hashlib
import secrets
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(HERE, '..', 'data'))
SCHEMA_SOURCE = os.path.join(DATA_DIR, 'seed.db')      # read schema ONLY from here
BLANK_OUT = os.path.join(DATA_DIR, 'seed_blank.db')
DEMO_OUT = os.path.join(DATA_DIR, 'seed_demo.db')


# ── password hashing (must match app.py _hash_password exactly) ────────────────
def hash_password(password):
    """PBKDF2-HMAC-SHA256, 16-byte salt, 200_000 iterations, base64(salt+hash).
       Byte-for-format-identical to app.py's _hash_password."""
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return base64.b64encode(salt + h).decode()


# ── schema extraction (reads only sqlite_master.sql, never any data rows) ──────
def read_schema_sql(source_db):
    if not os.path.exists(source_db):
        raise FileNotFoundError(
            f"Schema source not found: {source_db}\n"
            "Expected the existing data/seed.db to read the schema from."
        )
    conn = sqlite3.connect(source_db)
    try:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE sql IS NOT NULL "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY CASE type WHEN 'table' THEN 0 "
            "                   WHEN 'index' THEN 1 ELSE 2 END, name"
        ).fetchall()
    finally:
        conn.close()
    # Each statement, terminated so executescript can run them in order.
    return ';\n'.join(r[0] for r in rows if r[0]) + ';'


def fresh_db(path, schema_sql):
    """Create a brand-new SQLite file at `path` with the given schema, no rows."""
    if os.path.exists(path):
        os.remove(path)
    # also clear any stale WAL/SHM siblings
    for ext in ('-wal', '-shm'):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    conn = sqlite3.connect(path)
    conn.executescript(schema_sql)
    conn.commit()
    return conn


def put_settings(conn, mapping):
    for k, v in mapping.items():
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', (k, str(v)))


# ── generic (non-identity) settings shared by both seeds ───────────────────────
# These mirror the app's own init_db defaults but hold NO founder identity.
GENERIC_SETTINGS = {
    'next_bill_number': '1',
    'next_lr_number': '1',            # generic start (real seed used 13453)
    'pod_overdue_days': '10',
    'default_hsn_sac': '996511',      # Goods transport by road
    'default_reverse_charge': '1',    # GTA most common
    'default_gst_pct': '5',           # 5% if forward charge for GTA
    'vehicle_type': 'LP',
    'freight_type': 'A1/A4',
    # migration flags pre-set so the app's one-time migrations no-op on a clean DB
    'payments_migration_done': '1',
    'recipient_name_consignor_fix': '1',
}

# Identity settings — BLANK for seed_blank.
BLANK_IDENTITY = {
    'supplier_name': '',
    'supplier_address': '',
    'supplier_gstin': '',
    'supplier_state_code': '',
    'supplier_pan': '',
    'supplier_phone': '',
    'supplier_email': '',
    'supplier_bank_name': '',
    'supplier_bank_account': '',
    'supplier_bank_ifsc': '',
    'default_consignor_name': '',
    'default_consignor_address': '',
    'default_consignor_gstin': '',
    'default_consignor_state': '',
    'client_name': '',
    'clients': '[]',
}


def build_blank(schema_sql):
    conn = fresh_db(BLANK_OUT, schema_sql)
    try:
        put_settings(conn, GENERIC_SETTINGS)
        put_settings(conn, BLANK_IDENTITY)
        put_settings(conn, {'setup_complete': '0', 'is_demo': '0'})
        # No users (setup wizard creates the owner). No bills / challans / ledger /
        # payments / freight_rates / recipients / diesel_vendors / transporters.
        conn.commit()
    finally:
        conn.close()


def build_demo(schema_sql):
    conn = fresh_db(DEMO_OUT, schema_sql)
    now = datetime.now()
    iso = now.isoformat()
    try:
        # ── settings: generic defaults + a CLEARLY-FAKE demo identity ──
        put_settings(conn, GENERIC_SETTINGS)
        put_settings(conn, {
            'supplier_name': 'DEMO ROADLINES (SAMPLE)',
            'supplier_address': 'Plot 1, Sample Transport Nagar, Kanpur (DEMO — not a real address)',
            'supplier_gstin': '09AAAAA0000A1Z5',   # valid GSTIN format, fake value
            'supplier_state_code': '09',
            'supplier_pan': 'AAAAA0000A',
            'supplier_phone': '99999 00000',
            'supplier_email': 'demo@example.com',
            'supplier_bank_name': 'DEMO BANK (SAMPLE)',
            'supplier_bank_account': '000000000000',
            'supplier_bank_ifsc': 'DEMO0000001',
            'default_consignor_name': 'SAMPLE TRADERS (DEMO)',
            'default_consignor_address': 'Sample Market, Kanpur (DEMO)',
            'default_consignor_gstin': '09BBBBB1111B1Z4',
            'default_consignor_state': '09',
            'client_name': 'SAMPLE BEVERAGES (DEMO)',
            'clients': '["SAMPLE BEVERAGES (DEMO)"]',
            'setup_complete': '1',
            'is_demo': '1',
            'next_bill_number': '4',   # after the 3 demo bills below
            'next_lr_number': '104',   # after the demo challans below
        })

        # ── one demo user: Demo / Demo, no forced password change ──
        conn.execute(
            '''INSERT INTO users (username, password_hash, full_name, role,
                                  is_active, must_change_password, created_at)
               VALUES (?,?,?,?,1,0,?)''',
            ('Demo', hash_password('Demo'), 'Demo User', 'admin', iso)
        )

        # ── fake freight rates with Hindi-ish place names ──
        rates = [
            # customer_name, party_code, location, twy, owy, lp_owy, lp_twy, tr_owy, tr_twy
            ('SAMPLE BEVERAGES (DEMO)', 'D01', 'RAMPUR',      120, 60,  4500, 8200, 6200, 11000),
            ('SAMPLE BEVERAGES (DEMO)', 'D02', 'BILHAUR',     90,  45,  3800, 7000, 5200, 9500),
            ('SAMPLE BEVERAGES (DEMO)', 'D03', 'AKBARPUR',    70,  35,  3200, 6000, 4400, 8200),
            ('SAMPLE BEVERAGES (DEMO)', 'D04', 'JAINPUR',     50,  25,  2600, 4800, 3600, 6600),
            ('SAMPLE BEVERAGES (DEMO)', 'D05', 'SHIVRAJPUR',  110, 55,  4200, 7700, 5800, 10400),
            ('SAMPLE BEVERAGES (DEMO)', 'D06', 'GHATAMPUR',   140, 70,  5000, 9000, 6900, 12200),
        ]
        for r in rates:
            conn.execute(
                '''INSERT INTO freight_rates
                     (customer_name, party_code, location, dist_twy_km, dist_owy_km,
                      lp_owy, lp_twy, trolla_owy, trolla_twy, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (*r, iso)
            )

        # ── a couple of demo transporters + diesel vendors (fake) ──
        conn.execute(
            '''INSERT INTO transporters (name, mobile, bank_details, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?)''',
            ('DEMO CARRIERS (SAMPLE)', '99999 11111', 'DEMO BANK / 000000000000',
             'Sample transporter for the demo', iso, iso)
        )
        conn.execute(
            '''INSERT INTO transporters (name, mobile, bank_details, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?)''',
            ('SAMPLE FREIGHT LINES (DEMO)', '99999 22222', '', '', iso, iso)
        )
        conn.execute(
            '''INSERT INTO diesel_vendors (name, location, notes, created_at, updated_at)
               VALUES (?,?,?,?,?)''',
            ('SAMPLE FUEL STATION (DEMO)', 'Kanpur (DEMO)', '', iso, iso)
        )

        # ── 3 sample bills with fake consignees ──
        consignor = 'SAMPLE TRADERS (DEMO)'
        bills = [
            # bill_no, date_offset_days, recipient_name(consignor/client), amount, taxable, place
            ('JL-0001', 14, 12000.0, 'RAMPUR'),
            ('JL-0002', 9,  8600.0,  'BILHAUR'),
            ('JL-0003', 3,  15400.0, 'GHATAMPUR'),
        ]
        for i, (bill_no, days_ago, amount, dest) in enumerate(bills, start=1):
            bdate = (now - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            conn.execute(
                '''INSERT INTO bills
                     (bill_no, bill_date, recipient_name, recipient_address, recipient_gstin,
                      state_code, trip_type, vehicle_no, freight_type, delivery_month,
                      client_name, total_amount, taxable_value, reverse_charge,
                      place_of_supply, hsn_sac, deliveries, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (bill_no, bdate, consignor, 'Sample Market, Kanpur (DEMO)', '09BBBBB1111B1Z4',
                 '09', 'One Way', f'UP78 DM {1000 + i}', 'A1/A4',
                 (now - timedelta(days=days_ago)).strftime('%b/%y').upper(),
                 'SAMPLE BEVERAGES (DEMO)', amount, amount, 1,
                 '09', '996511', '[]', bdate)
            )

        # ── matching demo challans (so the ledger entries can link) ──
        challan_ids = []
        challans = [
            ('LR-101', 14, 'RAMPUR',    'SAMPLE BEVERAGES (DEMO)'),
            ('LR-102', 9,  'BILHAUR',   'SAMPLE BEVERAGES (DEMO)'),
            ('LR-103', 3,  'GHATAMPUR', 'SAMPLE BEVERAGES (DEMO)'),
        ]
        for lr_no, days_ago, dest, consignee in challans:
            cdate = (now - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            cur = conn.execute(
                '''INSERT INTO challans
                     (lr_no, challan_date, consignor_name, consignor_address,
                      consignee_name, consignee_address, from_city_state, to_city_state,
                      status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (lr_no, cdate, consignor, 'Sample Market, Kanpur (DEMO)',
                 consignee, f'{dest} (DEMO)', 'KANPUR, UTTAR PRADESH',
                 f'{dest}, UTTAR PRADESH', 'billed', cdate, cdate)
            )
            challan_ids.append(cur.lastrowid)

        # ── sample ledger entries (fake trips) ──
        # link to the demo transporter (id 1) and challans above
        ledger = [
            # gr_no, days_ago, station, mt_qty, freight, adv_cash, diesel, challan_idx
            ('GR-9001', 14, 'RAMPUR',    9.0, 12000.0, 2000.0, 3000.0, 0),
            ('GR-9002', 9,  'BILHAUR',   7.5, 8600.0,  1000.0, 2500.0, 1),
            ('GR-9003', 3,  'GHATAMPUR', 12.0, 15400.0, 3000.0, 4000.0, 2),
        ]
        for gr_no, days_ago, station, mt, freight, adv_cash, diesel, cidx in ledger:
            edate = (now - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            conn.execute(
                '''INSERT INTO ledger_entries
                     (challan_id, entry_date, gr_no, vehicle_no, station, trip_type,
                      mt_qty, freight, advance_cash, advance_account, diesel,
                      diesel_vendor_id, transporter_id, pod_received, paid,
                      created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (challan_ids[cidx], edate, gr_no, f'UP78 DM {1000 + cidx + 1}', station,
                 'One Way', mt, freight, adv_cash, 0.0, diesel,
                 1, 1, 1 if days_ago > 5 else 0, 0, edate, edate)
            )

        conn.commit()
    finally:
        conn.close()


def verify(path, label):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        print(f"\n=== {label}: {path} ===")
        print(f"tables ({len(tables)}): {', '.join(tables)}")
        for t in ('users', 'bills', 'challans', 'ledger_entries', 'payments',
                  'freight_rates', 'transporters', 'diesel_vendors'):
            try:
                n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                print(f"  {t:16s}: {n}")
            except sqlite3.Error:
                print(f"  {t:16s}: (missing)")
        def s(k):
            r = conn.execute('SELECT value FROM settings WHERE key=?', (k,)).fetchone()
            return '' if r is None else r[0]
        print(f"  setting supplier_name = {s('supplier_name')!r}")
        print(f"  setting supplier_gstin= {s('supplier_gstin')!r}")
        print(f"  setting setup_complete= {s('setup_complete')!r}")
        print(f"  setting is_demo       = {s('is_demo')!r}")
    finally:
        conn.close()


def main():
    print(f"Reading schema (schema only, no data) from: {SCHEMA_SOURCE}")
    schema_sql = read_schema_sql(SCHEMA_SOURCE)

    build_blank(schema_sql)
    build_demo(schema_sql)

    verify(BLANK_OUT, 'BLANK')
    verify(DEMO_OUT, 'DEMO')
    print("\nDone. data/seed.db was NOT modified.")


if __name__ == '__main__':
    main()
