# Munshi session context — admin/operator portals, Supabase migration, naming check

Written as a handoff/reference doc summarizing everything done in this session. Munshi is a Flask + SQLite app for Indian road-transport businesses (freight billing, GST invoices, driver ledger, payments) — see the project's own `CLAUDE.md` for the full product/architecture description.

---

## 1. Admin / Operator login portals

**Problem:** the app had one shared `/login` page for every account regardless of role.

**What was built:**
- `/admin/login` and `/operator/login` — role-scoped sign-in links. Each checks the account's role after a correct password and refuses entry (with a pointer to the correct link) if the role doesn't match the portal.
- `/login` kept unchanged as the generic fallback (used by internal redirects like session-timeout, which don't know the visitor's role in advance).
- Files: `munshi/api/auth.py` (`admin_login()`, `operator_login()`, shared `_portal_login()` helper), `app.py` (`_PUBLIC_ENDPOINTS`), `templates/login.html` (portal branding + "switch portal" link).

**Status:** done, tested, committed and pushed to both `refactor/enterprise-architecture` and `master` (fast-forward, no conflicts) — live on Render already.

---

## 2. The Render data-loss problem

**Symptom:** every Render redeploy (or container restart) wiped all data — users, bills, ledger entries, everything.

**Root cause:** Munshi stores everything in one SQLite file (`bills.db`). The `Dockerfile` sets `MUNSHI_APP_DIR=/data`, but `/data` is just ephemeral container disk on Render — not an attached persistent volume. Every redeploy discards the old container and boots a fresh one from the image, so the database resets to the blank seed each time.

**Two possible fixes discussed:**
- Attach a Render persistent Disk (needs a paid instance plan — Render's free tier doesn't offer disks).
- Move the data store to a real external database — **chosen**, using Supabase's free Postgres tier.

---

## 3. Supabase project

- **Project ref:** `pdonxlcfgtgixbyjyfvq` (name "MUNSHI", org "Aditya-Gautam37's Org")
- **Credentials:** all in the repo's local `.env` (gitignored, never committed) — `DATABASE_URL` (pooler connection, port 6543, IPv4-reachable — the direct `db.*.supabase.co` host is IPv6-only and doesn't resolve on most networks), `SUPABASE_URL`, `SUPABASE_ANON_KEY` (new `sb_publishable_...` format), `SUPABASE_SERVICE_ROLE_KEY` (new `sb_secret_...` format — bypasses RLS, never expose client-side).
- **Real organization bootstrapped:** `BUILDANTA PRIVATE LIMITED`, id `ba4ba71c-e192-4d02-bcce-38d7d1e83e11` — also saved in `.env` as `MUNSHI_ORGANIZATION_ID` for local runs; **still needs to be added to Render's environment variables** for the hosted app to use it.

### SQL migrations applied (live on the Supabase project)
- `sql/001_baseline_schema.sql` — the original multi-tenant schema: `organizations`, `memberships`, `bills`, `ledger_entries`, `payments`, `challans`, etc. — every table keyed by `organization_id`, Postgres Row-Level Security (RLS) enabled, `current_org_id()` helper reading a JWT claim.
- `sql/002_ledger_settlement_fields.sql` — added 7 columns to `ledger_entries` (`shortage`, `leakage`, `breakage`, `unloading`, `detention`, `toll_tax`, `excess_km`) that existed in SQLite but were missing from the original Postgres baseline — needed for the transporter-balance formula to match exactly.
- `sql/003_auth_tables.sql` — added a non-tenant `users` table (mirrors SQLite's `users` table: `username` PK, PBKDF2 `password_hash`, role, etc.) since the existing multi-tenant `memberships` table assumes Supabase Auth owns credentials and has no password column at all — it can't hold this app's homegrown login. Login-lockout tracking reuses the *existing* `login_failures` table (already org-scoped) rather than adding a duplicate.

Each `.sql` file has a matching Alembic migration under `munshi/pg/migrations/versions/` for future use, but in practice each was applied directly via a Python/psycopg script against the live pooler connection (Alembic through a transaction-mode pooler has known issues with its own locking).

---

## 4. Phase 1 — proving the Postgres/RLS/JWT plumbing works

Built self-contained, **not yet wired into the running app**, verified with pytest against the live project:
- `munshi/pg/auth.py` — `verify_supabase_jwt()`, validates a real Supabase-issued JWT via JWKS (confirmed the project uses ES256/JWKS, not a legacy shared secret).
- `munshi/pg/services/organization_service.py`, `transporter_service.py` — first, deliberately trivial service-layer examples.
- `tests/test_pg_tenant_isolation.py` — proves RLS actually blocks cross-org reads **and** writes (not just a comment claiming it does).
- `tests/test_pg_jwt_auth.py` — proves a real Supabase-issued token round-trips through the verifier.

---

## 5. Phase 2 — money-critical logic, ported and tested standalone

Still self-contained under `munshi/pg/services/`, not yet wired into `app.py`:
- `numbering_service.py` — race-free bill/LR number allocation via real `SELECT ... FOR UPDATE` row locking (proven under actual concurrent load — 10 threads, zero duplicates/gaps). Replaces SQLite's scan-and-retry scheme, which could never rigorously guarantee that.
- `payment_service.py` — `get_party_balance()`, the `payments`-table-as-single-source-of-truth auto-payment mirroring convention, manual payment recording. Every query explicitly filters by `organization_id` (defense-in-depth beyond RLS, since the app's own connection runs as the RLS-bypassing `postgres` role).
- `bill_service.py` — `create_bill()`: reuses `compute_gst_split()` from `munshi/utils/gst.py` **unchanged** (zero risk to GST math), wired to the new numbering service.
- `ledger_service.py` — `ledger_balance()` and `mark_ledger_paid()`, faithfully preserving two SQLite quirks on purpose (documented, not silently "fixed"): a `paid_amount` of 0 falls back to the computed balance rather than recording zero, and a trip with no assigned transporter silently skips the auto-payment mirror.

11 new tests, all passing against the live project.

---

## 6. Phase 3 — wiring the actual live app to Postgres

This is the part that matters for actually fixing the Render problem. **Single-business deployment, not multi-tenant** — kept the existing homegrown login/session system exactly as-is rather than adopting Supabase Auth.

### Mechanism
- `PG_MODE = bool(os.environ.get('DATABASE_URL'))`, `ORG_ID = os.environ.get('MUNSHI_ORGANIZATION_ID')` — plain module globals in `app.py`, mirroring how `DB_PATH` already works.
- Every touched function/route gets `if PG_MODE: <postgres path> else: <original SQLite code, completely unchanged>`.
- All `munshi.pg` imports are deferred (inside the `if PG_MODE:` branch) — the desktop PyInstaller build explicitly excludes `psycopg`/`alembic`/`jwt` (`build/munshi.spec`), so these must never be imported unconditionally at module load time.
- New non-tenant auth table + service: `munshi/pg/auth_models.py` (`User`), `munshi/pg/services/user_service.py` (mirrors `munshi/repositories/user_repository.py`'s exact function surface, so the auth business-logic layer above it needs zero changes).
- New `munshi/pg/services/settings_service.py` (firm identity, reuses the existing `Setting` model) and `diesel_vendor_service.py` (needed as a small dependency to unblock ledger entry creation).
- `munshi/pg/bootstrap_single_org.py` — the one-time script that created the real organization (refuses to run again if one already exists).

### What's now Postgres-backed (verified end-to-end via `tests/test_pg_smoke.py`)
- Login, users, lockout, firm settings
- Bills — create + view
- Ledger entries — create, edit, mark paid (+ transporter balance)
- Payments — record + balance views, payments hub
- Transporters — add + delete

### What's still on the local SQLite file (still lost on redeploy) — explicit scope boundary, not an oversight
Challans, diesel-vendor add/delete forms, reports, dashboard KPIs, search/trip lookup, AI photo extraction, recycle bin, the `/audit` log page, backup/Google Drive/license features.

### A few real bugs found and fixed along the way
- `psycopg.errors.DuplicatePreparedStatement` — Supabase's pooler can route successive queries to different backend connections; fixed by disabling psycopg3's server-side prepared statement cache (`prepare_threshold=None`) in `munshi/pg/database.py`.
- `load_dotenv(override=True)` in `app.py` re-injects `.env`'s `DATABASE_URL` even if a test tries to unset it first — meant `PG_MODE` would silently default to `True` during the original SQLite test suite. Fixed by having `tests/test_smoke.py` force `PG_MODE = False` explicitly after import, rather than relying on the env var being absent.
- `operator does not exist: bigint = character varying` — Flask URL route params are always strings; SQLite compares loosely, Postgres doesn't. Fixed by casting `party_key` to `int` wherever it's compared against a `BigInteger` column (`transporter_id`/`diesel_vendor_id`).
- A CSRF token bug in the new tests themselves: `/setup` and `/login` both call `session.clear()` on success, wiping the just-seeded CSRF token — needed a fresh page load before extracting the token for the next POST.

### Test results
**54 tests passing**: the original 37 SQLite tests (completely unaffected — confirms `PG_MODE=False` desktop/default behavior is untouched), plus 17 against the live Supabase project (2 from Phase 1, 11 from Phase 2, 4 new end-to-end smoke tests covering setup→login→create bill→view it, ledger entry→mark paid→balance check, and manual payment→balance reduction).

### Not done yet
**This has not been deployed.** Everything above is verified locally and against the live Supabase project, but not pushed to GitHub or live on Render. To actually fix the data-loss problem in production:
1. Push these changes to GitHub (`master`, which Render watches).
2. Add `MUNSHI_ORGANIZATION_ID=ba4ba71c-e192-4d02-bcce-38d7d1e83e11` to Render's environment variables (alongside the `DATABASE_URL`/`SUPABASE_*` vars presumably already there from earlier setup).
3. Redeploy and verify a real bill/ledger entry survives a second redeploy.

The approved implementation plan for this phase is saved at `.claude/plans/streamed-giggling-crescent.md`.

---

## 7. "Munshi" naming/domain check

Asked whether "Munshi" is available for hosting — turned out to mean "is another app already using this name," not domain WHOIS.

**Finding: the name is already fairly crowded in this exact space** (business/finance apps for India):
- **Munshi POS** — restaurant point-of-sale for small/medium Indian restaurants ([Capterra](https://www.capterra.com/p/191698/Munshi-POS/))
- **Munshi: Money Manager** — personal finance tracker, iOS + Android
- **My Munshi** — litigation management for lawyers (Supreme/High/District courts)
- **Munshi by Synavos** — payments management for SMEs, retail-focused — **closest collision**: also India-focused, also SME/business financial-operations software, identical name
- **Wealth Munshi** — financial advisory/investment app
- **MUNSHI Healthcare** — hospital/patient-data system (open source)
- **munshi.app** — domain already live with its own product
- `munshi.com` — registered since 1999, not available

**Takeaway:** worth considering a distinguishing variant (e.g., "MunshiGST," "MunshiFreight," "TruckMunshi") before investing further in branding, domain purchase, or trademark for the bare name "Munshi."
