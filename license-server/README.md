# Munshi License Server

The small always-on program that lets you **switch each customer on or off**. It is how you enforce payment without ever touching a customer's data.

**Important:** this server only ever receives a license key, a truck *count* (a number), and a version string. It never sees any bilty, ledger, or customer business data. That is deliberate — it keeps the "your data never leaves your laptop" promise true.

---

## What it does

- Holds one row per customer: their key, plan, and expiry date.
- Answers the Munshi app's periodic "is this key still active?" check (`POST /verify`).
- Gives you a **web dashboard** (`/admin`) to create keys and suspend / reactivate / extend customers with buttons.

Statuses it returns to the app:

| Status | What the customer experiences |
|---|---|
| `active` | Normal — everything works |
| `grace` | Expired but within the grace window (default 14 days) — still works, shows a yellow "please renew" banner |
| `expired` | Past grace — Munshi goes **read-only** (they can still *see* their data, just not add new entries) until they renew |
| `suspended` | You turned them off manually — read-only |
| `not_found` | Key not recognised — read-only |

**Their data is never deleted, ever** — even when off. Read-only is the strongest lever we use.

---

## Run it locally (to test)

```bash
cd license-server
pip install -r requirements.txt
MUNSHI_ADMIN_PASSWORD="pick-a-password" MUNSHI_ADMIN_TOKEN="pick-a-long-random-token" python3 app.py
```

Open **http://127.0.0.1:5090/admin**, log in with the password, and add a customer.

---

## Settings (environment variables)

| Variable | What it's for |
|---|---|
| `MUNSHI_ADMIN_PASSWORD` | Password for the `/admin` web dashboard (you use this) |
| `MUNSHI_ADMIN_TOKEN` | Secret token for the JSON API / scripts (optional) |
| `LICENSE_FLASK_SECRET` | Keeps you logged in across restarts (set any long random string in production) |
| `MUNSHI_GRACE_DAYS` | Grace window after expiry, in days (default 14) |
| `PORT` | Port to run on (default 5090) |

If a secret isn't set, that part **fails closed** (the dashboard/API stays locked) — it is never left wide open.

---

## Point Munshi at it (go-live)

On each customer's install, set one line in their `.env` (next to `Munshi.exe`):

```
LICENSE_SERVER_URL=https://license.yourdomain.in
```

That's it. The customer opens Munshi → **License** → pastes the key you sent → done. Munshi checks the key quietly (about weekly), sending only the key + truck count.

Leave `LICENSE_SERVER_URL` **empty** and Munshi runs free/unlicensed (which is how your free-trial pilots run — you don't need this server for them).

---

## Deploy it for real (when you start charging)

A ₹300–600/month tiny cloud server (DigitalOcean / Hetzner / Contabo) is plenty. High-level:

1. Rent the smallest Linux server; point a subdomain (e.g. `license.yourdomain.in`) at it.
2. Copy this `license-server/` folder up; `pip install -r requirements.txt`.
3. Run it behind nginx + gunicorn with HTTPS (Let's Encrypt is free). Set the environment variables above (real password + token).
4. Back up `licenses.db` daily (it's tiny).

(Ask me when you're ready — I'll give you the exact copy-paste commands for the provider you pick.)

---

## Security hardening (before you go public)

The core is solid — auth fails closed, all database queries are injection-safe, keys are strong, inputs are bounded, and the admin pages escape HTML. Do these when you deploy publicly:

1. **Run behind HTTPS** (nginx + free Let's Encrypt) and set `LICENSE_HTTPS=1` so the login cookie is marked `Secure`.
2. **Use a long random `MUNSHI_ADMIN_PASSWORD`** and set `LICENSE_FLASK_SECRET` (a long random string — keeps you logged in across restarts).
3. **Rate-limit at nginx** — the single highest-value protection (stops `/verify` flooding and password brute-forcing):
   ```nginx
   limit_req_zone $binary_remote_addr zone=verify:10m rate=10r/s;
   limit_req_zone $binary_remote_addr zone=login:10m  rate=5r/m;
   location = /verify      { limit_req zone=verify burst=20 nodelay; proxy_pass http://127.0.0.1:5090; }
   location = /admin/login { limit_req zone=login  burst=3;          proxy_pass http://127.0.0.1:5090; }
   location /              { proxy_pass http://127.0.0.1:5090; }
   ```
4. **Back up `licenses.db` daily** (it's tiny — a nightly copy is enough).

Already built in: `SameSite=Lax` + `HttpOnly` cookies (CSRF defence), a 64 KB request-body cap, a big-number input guard on `/verify`, an open-redirect guard on login, and a self-trimming verify log. (Full CSRF tokens on the dashboard forms are optional belt-and-suspenders on top of SameSite.)

---

## Manage customers

**Easiest — the dashboard:** open `/admin`, log in. You'll see every customer with their status, and buttons: **Suspend**, **Reactivate**, **+1 month**, **+1 year**. Add a customer with the form at top; the new key appears in the green bar — send it to them.

**By script/API (optional):** with the admin token,

```bash
# create a 12-month Growth-tier key
curl -X POST http://127.0.0.1:5090/provision \
  -H "Authorization: Bearer $MUNSHI_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"customer_name":"Sharma Transport","tier":"growth","months":12,"phone":"98xxxxxxx"}'

# suspend / reactivate / extend
curl -X POST http://127.0.0.1:5090/license/MUNSHI-XXXX-XXXX-XXXX-XXXX/suspend    -H "Authorization: Bearer $MUNSHI_ADMIN_TOKEN"
curl -X POST http://127.0.0.1:5090/license/MUNSHI-XXXX-XXXX-XXXX-XXXX/reactivate -H "Authorization: Bearer $MUNSHI_ADMIN_TOKEN"
curl -X POST http://127.0.0.1:5090/license/MUNSHI-XXXX-XXXX-XXXX-XXXX/extend -H "Authorization: Bearer $MUNSHI_ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"months":12}'
```

---

## Tiers

| Tier | Trucks | (your pricing) |
|---|---|---|
| `starter` | 1–3 | ₹800/mo |
| `growth` | 4–10 | ₹1,000/mo |
| `pro` | 11–30 | ₹1,200/mo |
| `fleet` | 31+ | custom |
