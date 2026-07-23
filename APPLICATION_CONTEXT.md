# Munshi — full application context

A complete picture of what this application is, how it's built, and what state it's in. For a log of *this session's* changes specifically (admin/operator portals, Supabase migration), see `SESSION_CONTEXT.md`.

---

## 1. What Munshi is

Munshi is software for small **Indian road-transport businesses** (goods transporters/GTAs) to run their day-to-day paperwork and money tracking. It replaces a paper notebook + Excel + WhatsApp-photos workflow with one app.

**Core value proposition:** photograph a handwritten LR/bilty (consignment note) and Google Gemini Vision reads it into structured fields — no typing. Everything else (billing, ledger, payments) flows from there.

**Who uses it:** the owner of a small transport company (a handful of trucks, a few staff) — not enterprise logistics. The product is deliberately simple, in Hindi or English, and originally designed to run **entirely offline on the owner's own Windows laptop** ("data never leaves the laptop" was the original privacy promise — see §7 for how this session's work changes that for the hosted variant).

**What it does, concretely:**
- **AI photo → bilty**: photograph a challan/LR, Gemini extracts fields into a draft you review and save.
- **Daily money ledger**: freight, driver advances (cash/account), diesel, POD (proof-of-delivery) settlement adjustments (shortage, leakage, breakage, unloading, detention, toll, excess km).
- **GST-compliant invoicing**: GTA/reverse-charge aware, CGST+SGST vs IGST split, e-invoice JSON export.
- **Payments**: a single `payments` ledger is the source of truth for who owes whom (client owes us / we owe transporter / we owe diesel vendor) — every "mark paid" checkbox mirrors into it automatically.
- **Proof-of-delivery photos, recycle bin, audit log, daily backups.**
- **English ⇄ Hindi toggle**, first-run setup wizard, role-based accounts (admin/operator).
- **Licensing**: a separate `license-server/` Flask app can phone-home to gate paid subscriptions (off by default).

---

## 2. Tech stack

- **Python 3 + Flask**, one main file `app.py` (~6,700 lines — a monolith on purpose, in active refactor toward a layered `munshi/` package — see §4).
- **SQLite** (`bills.db`) as the original/default single-tenant datastore. **As of this session, an alternate Postgres/Supabase-backed mode also exists** — see §7.
- **Jinja2 templates** (`templates/`, 38 files) + vanilla JS/CSS (`static/`). No build step, no npm, no JS framework — Flask serves everything server-rendered.
- **Google Gemini** (`google-genai`) for OCR/vision extraction. App works without a key; AI features just turn off.
- **SQLAlchemy** (2.x) is layered in progressively for parts of the app (see §4) — both a SQLite engine (`munshi/database/engine.py`) and, new this session, a Postgres engine (`munshi/pg/database.py`).
- **Waitress** as the production WSGI server (`waitress.serve(...)`), multi-threaded.
- **PyInstaller** builds the Windows/Mac desktop installer (`build/munshi.spec`) from the same codebase.
- **Docker** for the hosted variant (`Dockerfile`), deployed on **Render**.

---

## 3. Repository map

```
app.py                      — the monolith: routes for bills/challans/ledger/payments/
                               reports/dashboard/extraction/settings/masters/backup/
                               license, plus init_db() (schema) and shared helpers.
munshi/
  api/auth.py                — /setup, /login, /admin/login, /operator/login, /users*
                                (fully extracted from app.py; registered via
                                add_url_rule, not a Blueprint, to preserve url_for names)
  services/auth_service.py   — login/setup/lockout/password business logic
  repositories/
    user_repository.py       — users table data access (SQLite <-or-> Postgres, see §7)
  models/                    — SQLAlchemy models mapped onto the SQLite schema
  database/
    legacy.py                — raw sqlite3 get_db()/teardown
    engine.py                — SQLAlchemy engine/session for the SQLite side
  utils/
    gst.py                   — compute_gst_split(), validate_gstin() (pure functions)
    formatting.py, i18n.py
  config.py                  — APP_DIR/DB_PATH/UPLOAD_DIR/BACKUP_DIR resolution,
                                secret-key handling
  pg/                        — Postgres/Supabase backend, added this session (see §7)
    models.py, auth_models.py, base.py, database.py, auth.py
    services/                — organization, transporter, diesel_vendor, numbering,
                                payment, bill, ledger, user, settings services
    migrations/               — Alembic env + versioned migrations (0001-0003)
    bootstrap_single_org.py
templates/                   — 38 Jinja2 files; base.html is the shell (sidebar, top
                               bar, English/Hindi toggle)
translations/hi.json         — flat English→Hindi map
static/                      — jl-app.css, style.css, PWA manifest/service worker
sql/                         — plain .sql mirrors of the Alembic migrations, applied
                               directly against the live Supabase project
tests/
  test_smoke.py               — 37 tests, SQLite-mode (boot/login/bills/ledger/
                               payments/GST/restore/extraction-merge/rate-list-import)
  test_pg_*.py                — 17 tests against the live Supabase project
  conftest.py                 — shared pg_session fixture
license-server/               — SEPARATE small Flask app, the paid-subscription
                               kill-switch. Not the product itself.
build/                        — PyInstaller spec + scripts for the desktop installer
data/seed*.db                 — blank + demo starter SQLite databases
Dockerfile, .dockerignore     — hosted/Render deployment image
.claude/plans/                — saved implementation plans from past planning sessions
```

---

## 4. Architecture notes

`app.py` is a **monolith being incrementally refactored** into a layered `munshi/` package (repository → service → API), domain by domain. As of this session:

- **Fully layered:** the auth/users domain (`munshi/api/auth.py` + `services/auth_service.py` + `repositories/user_repository.py`).
- **Partially layered:** bills/ledger/payments/transporters now have a *second*, Postgres-backed implementation (`munshi/pg/services/`) that a `PG_MODE` flag can route to (see §7) — but the original inline-SQL versions in `app.py` are the ones still used for the SQLite/desktop path and remain untouched.
- **Still fully inline in `app.py`:** challans, masters (diesel vendors), settings/rate-list, search/vehicle-history/trip, AI extraction, reports, dashboard, recycle bin, audit view, backup/Drive/license.

**Two deployment targets, one codebase:**
1. **Desktop installer** (PyInstaller) — single-tenant, SQLite-only, runs on the customer's own laptop, offline-capable. `build/munshi.spec` explicitly excludes `psycopg`/`alembic`/`jwt` from this build.
2. **Hosted** (Docker on Render) — was also SQLite-only until this session; now has an opt-in Postgres-backed mode for one business (see §7). This is where "data never leaves the laptop" no longer applies — a fact that needs a content/messaging audit (setup wizard copy, license page, `README-INTERN.md`) before any real hosted customer signs up, per an earlier planning note.

**Money-critical code** (explicitly called out in `CLAUDE.md` as needing extra care, tested by name in `tests/test_smoke.py`):
- `get_party_balance()` / `_client_charges()` / `_transporter_charges_net()` / `_diesel_vendor_charges()` / `_payments_total()` (`app.py`) — the `payments` table is the single source of truth for every balance shown anywhere in the app.
- `_auto_payment_upsert()` / `_auto_payment_remove()` — the idempotent mirroring convention that keeps a "mark paid" checkbox and the `payments` table in sync.
- `compute_gst_split()` (`munshi/utils/gst.py`) — pure function, CGST+SGST vs IGST, reverse-charge handling, rupee rounding rules.
- `_alloc_bill_no()` / `find_unique_lr_no()` — collision-safe sequential numbering (SQLite: scan-and-retry; Postgres: real row locking, see §7).

---

## 5. Database schema (SQLite, the original/default)

Single file `bills.db`, created by `init_db()` (`app.py`) via idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` — no destructive migrations, ever. Key tables: `users`, `settings` (flat KV), `bills`, `challans`, `ledger_entries`, `payments`, `transporters`, `diesel_vendors`, `freight_rates`, `recipients`, `vehicles`, `drivers`, `extractions`/`extracted_invoices`/`ledger_extractions`, `audit_log`, `login_failures`, plus `*_archive` shadow tables for the recycle bin, `license_state`, `google_drive_state`.

---

## 6. Testing

```
python -m pytest tests/ -q
```
Must stay green (37 SQLite tests; +17 Postgres tests if `DATABASE_URL` is set, otherwise those skip cleanly). Covers: boot/login/lockout, bill creation + GST math (3 cases), the "split-brain balance" regression guard, atomic WAL-safe restore, challan/invoice AI-extraction merge logic (4 cases), ledger/POD settlement math (9 cases), duplicate-GR warning, freight rate-list Excel import (5 cases), Google Drive restore-on-boot.

---

## 7. This session's work — Postgres/Supabase migration (summary; full detail in `SESSION_CONTEXT.md`)

**Trigger:** the hosted Render deployment kept losing all data on every redeploy, because Render's container disk is ephemeral and the app stored everything in a local SQLite file.

**Fix, in three stages:**
1. Proved a real multi-tenant Postgres/RLS/JWT stack works (`munshi/pg/`), against a live Supabase project — built for a *possible future* multi-customer SaaS version, not required for the immediate fix.
2. Ported the money-critical logic (bills/GST, ledger balances, payments, race-free numbering) to that Postgres stack, standalone and tested.
3. **Actually wired the live `app.py` to it** for this one business (not multi-tenant — kept the existing homegrown login as-is): a `PG_MODE` flag switches login/settings/bills/ledger/payments/transporters between SQLite and Postgres per-request, while everything not yet migrated (challans, reports, extraction, etc.) stays on SQLite.

**Current status:** code complete and tested locally (54 passing tests, including live end-to-end runs against Supabase) but **not yet deployed** — needs pushing to GitHub and `MUNSHI_ORGANIZATION_ID` added to Render's environment variables before it actually stops the data loss in production.

**Real organization id for this business:** `ba4ba71c-e192-4d02-bcce-38d7d1e83e11` (BUILDANTA PRIVATE LIMITED), in `.env` as `MUNSHI_ORGANIZATION_ID`.

Also this session: added role-scoped `/admin/login` and `/operator/login` portals (separate from the Supabase work) — already deployed and live.

---

## 8. Naming

"Munshi" as a bare product name is already used by several unrelated apps in the same India/SME/finance space (Munshi POS, Munshi Money Manager, My Munshi, Munshi by Synavos, Wealth Munshi) — `munshi.com` and `munshi.app` are both taken. Worth a distinguishing variant (e.g. "MunshiGST," "TruckMunshi") before further branding/domain/trademark investment. Full detail in `SESSION_CONTEXT.md` §7.
