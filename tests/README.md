# Smoke tests

Fast guard so a future change can't silently break the money math or the
core happy path (boot → login → create a bill → record a client payment).

## Run

```
python3 -m pytest tests/ -q
```

Just check the file collects (no execution):

```
python3 -m pytest tests/ --collect-only -q
```

## First time? Install pytest

`pytest` may not be installed yet. If you see `No module named pytest`:

```
python3 -m pip install pytest
```

(Flask and the app's other dependencies are already needed to run Munshi, so
no extra installs beyond `pytest` itself.)

## What it covers

1. App boots and `/health` returns `ok`.
2. Login as `Owner`/`Owner`, then the forced first-login password change.
3. `POST /bill/new` persists a bill and the bill view renders `200`.
4. Recording a client payment moves the outstanding balance the SAME way on
   both money sources (dashboard KPI vs payments hub). This currently
   **xfails** on purpose — it guards the known "split-brain" client-outstanding
   bug (dashboard reads `bills.client_paid`, the payments hub reads the
   `payments` table). When the Phase-1 single-source-of-truth fix lands, this
   test starts passing (xpass) — that's the signal to delete the `xfail`
   marker in `test_smoke.py`.
5. The money-math helpers `amount_in_words_inr` and `compute_gst_split` return
   sane values (Lakh/Thousand words, RCM = zero tax, same-state CGST+SGST,
   inter-state IGST).

## Safe by design

Every test runs against a throwaway copy of the database in a temp folder. The
real `bills.db`, `backups/`, and `uploads/` next to the app are never touched.
