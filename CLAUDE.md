# Munshi — project guide (read me first)

This file is context for **Claude** (in VS Code / Claude Code). If you're the intern's AI assistant, read this before doing anything so you understand the project.

## What this app is
**Munshi** is a **local-first desktop app for small Indian road-transport businesses** (goods transporters). It runs **offline on the owner's own Windows laptop**; the data **never leaves the laptop** (that privacy is the whole product promise). It does:
- **AI photo → bilty**: photograph a handwritten LR/bilty (consignment note) and Google Gemini Vision reads it into structured fields (no typing).
- **Daily money ledger** (freight, driver advances, diesel), **Proof-of-Delivery** photos, **GST-compliant invoicing** (GTA / reverse-charge aware), and **payments** (who owes whom).
- **English ⇄ Hindi** toggle, **daily auto-backup**, and a first-run **setup wizard**.

The product brand is **"Munshi."** On printed invoices the *supplier* name is the customer's own firm (from Settings), never "Munshi."

## Tech stack (deliberately simple)
- **Python 3 + Flask**, one main file `app.py` (~6,000 lines — a monolith on purpose, easy to navigate).
- **SQLite**, a single file `bills.db` (created on first run). No server DB.
- **Jinja2 templates** in `templates/` + **vanilla JS** + custom CSS in `static/jl-app.css`. No build step, no npm — Flask serves everything.
- **Google Gemini** (google-genai) for the OCR. Works without a key (AI features just turn off).
- A **separate** tiny Flask app in `license-server/` — the paid-subscription kill-switch. It is NOT the product; don't confuse the two.

## How to run it (Windows)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        REM optional: add a free Gemini key for the photo-reader
python app.py                  REM opens http://127.0.0.1:5056
```
First launch shows the **setup wizard** (`/setup`) — enter a firm name + create a login. To load fake sample data instead, click "Load sample demo data" on the wizard.

## Map of the code (where things live)
- `app.py` — everything, in rough order: app config → `init_db()` (schema + idempotent migrations) → helpers → **auth** (`/login`, `/change-password`) → **setup wizard** (`/setup`, `_require_setup`) → **bills** (`/bill/*`) → **challans** (`/challan/*`) → **ledger** (`/ledger/*`) → **payments** (`/payments/*`) → **reports** → **AI extraction** (Gemini prompts + `/extract`) → **license client** (phone-home) → **backup + Data Vault + `/restore`** → **i18n** (`t()`, `/lang/<code>`).
- `templates/base.html` — the shell every page extends (sidebar nav, top bar, the English/Hindi toggle).
- `translations/hi.json` — flat English→Hindi map (211+ keys). Add Hindi here.
- `tools/make_seeds.py` — regenerates the blank + demo starter databases.
- `tests/test_smoke.py` — pytest smoke tests (boot, login, bill, payment math). Keep them green.
- `build/` — PyInstaller scripts + `munshi.spec` to make the Windows/Mac installer.
- `data/seed*.db` — starter databases (all blank/fake — no real business data).

## Conventions
- **SQL is always parameterized** (`?` placeholders) — never string-format user input into SQL.
- **CSRF**: every POST form includes a hidden `csrf_token` (read from `session['csrf_token']`). Copy the pattern when adding forms.
- **i18n**: wrap any new user-visible English text as `{{ t('Your text') }}` and add `"Your text": "हिंदी"` to `translations/hi.json`. Untranslated strings safely fall back to English.
- Helpers are prefixed `_`; each route is its own function.
- Keep it English by default; only the Hindi toggle switches language.

## Handle with extra care (test after touching)
These work — verify with the smoke tests after any change:
1. **Money/payments** — the `payments` table is the single source of truth; the dashboard, reports, and payments hub all read `get_party_balance()`. Don't reintroduce reading the old paid-flags.
2. **GST invoice math** — `compute_gst_split()` + `bill_view.html`. Invoices are legal documents; be precise.
3. **Setup wizard / first-run gating** — `_require_setup` + the `setup_complete` migration. Don't lock existing installs out of login.

## Test before you commit
```
pip install pytest
python -m pytest tests/ -q      REM must stay green (9 passing)
```
Also just run the app and click through the screen you changed. See `TASKS.md` for what to work on and `README-INTERN.md` for a fuller setup walkthrough.
