# Munshi — intern task list

Work top to bottom. **Always** run the app + `python -m pytest tests/ -q` (must stay green) before calling a task done. Ask your Claude (VS Code) for help — point it at `CLAUDE.md`.

---

## 🌱 Warm-up tasks (do these first — get comfortable)

- [ ] **W1. Run it.** Start the app (`python app.py`), complete the setup wizard, create one test bill, and click every menu item. Also click the **English | हिंदी** toggle and watch the app switch. Goal: understand what the app does.
- [ ] **W2. Green tests.** Run `python -m pytest tests/ -q` and confirm **9 passed**. Read `tests/test_smoke.py` to see what's checked.
- [ ] **W3. Your first change (safe).** Pick ONE screen that still shows English labels (see the Hindi task below for which), translate 3–5 of its labels: wrap each in `{{ t('The text') }}` in the template and add `"The text": "हिंदी"` to `translations/hi.json`. Reload with the Hindi toggle on and see your words appear. Commit it. This teaches the translation pattern.

---

## 🌐 Priority A — finish the Hindi translation

The app **frame** (menu, top bar) + these screens are already translated: dashboard, login, setup, change-password, error, challans list, ledger, payments hub, settings, new bill.
**Still need translating** (wrap visible English in `{{ t('...') }}` + add to `translations/hi.json`):
`masters.html`, `rate_list_editor.html`, `report_diesel.html`, `report_transporters.html`, `summary.html`, `to_bill.html`, `trip_view.html`, `challan_review.html`, `challan_upload.html`, `users.html`, `audit.html`, `license.html`, `recycle_bin.html`, the `extract_*` and `ledger_extract_*` pages.
- [ ] **A1.** Translate each remaining screen. Use **natural transporter Hindi** (the words a Kanpur munshi uses: खाता, चालान, भाड़ा, गाड़ी, बकाया), not formal/Google-translate Hindi. Reuse existing keys in `hi.json` where the same word appears.
- [ ] **A2. Do NOT translate:** `bill_view.html` and `summary_view.html` (those are the printed GST invoices — they stay English by law), plus GSTINs, numbers, and the "Munshi" brand.
- Verify: toggle Hindi, visit each screen, confirm no English labels remain (and nothing is blank).

## 🎨 Priority B — design polish
- [ ] **B1.** The login and setup screens use a generic purple gradient — make the look calmer and more distinctive/trustworthy (this is trust-heavy software for non-technical users). Keep it simple and consistent: one accent colour, big tap-friendly fields, clear buttons.
- [ ] **B2.** Sweep for consistency across screens (button styles, spacing, empty-state messages). Everything is in `static/jl-app.css` + the templates.
- Verify: it still works on a narrow window (owners use laptops and phones).

## 🔧 Priority C — technical items (test carefully after each)
- [ ] **C1. Code-sign the app** so customers don't see the "unverified publisher / can't check for malware" warning. Windows needs a code-signing certificate; Mac needs an Apple Developer ID + notarization. Research the cheapest legit option and wire it into `build/`. (Ask Yash before buying anything.)
- [ ] **C2. Upgrade bundled Python** from 3.9 (end-of-life) to 3.11+: update `build/munshi.spec` / the build scripts and the GitHub Actions workflow, rebuild, and smoke-test the installer.
- [ ] **C3. Split `app.py` into modules** (Flask blueprints) — start with ONE area (e.g. move the setup/settings/identity code into `identity.py`), confirm the app still runs + tests pass, then do another. Small steps, test each. Don't do it all at once.

## 🐞 Priority D — bugs & tests
- [ ] **D1.** Add more smoke tests to `tests/test_smoke.py`: creating a challan, creating + marking-paid a ledger entry, and the AI extraction with a **mocked** Gemini response (don't call the real API in tests).
- [ ] **D2.** Confirm the recycle-bin (undo delete) works for bills, challans, and ledger entries — delete one of each, then restore it from `/recycle-bin`.
- [ ] **D3.** Log any bug you hit while using the app, with steps to reproduce, and fix the small ones.

---

### Definition of done (every task)
1. The app still starts and the screen you changed works when you click it.
2. `python -m pytest tests/ -q` is still green.
3. You committed with a clear message.
4. If you touched money, invoices, or the login/setup flow — you tested those extra carefully (see `CLAUDE.md`).
