# Data Dictionary
*Companion to TECHNICAL_HANDOVER.md Part VII*

**Snapshot date**: 2026-05-10
**Schema source**: `bills.db` (live production)
**Generation**: `PRAGMA table_info(<table>)` per table.

---

## How to read this

Each table below lists every column with its SQL type and any constraints (`PK` = primary key, `NOT NULL`, `default=`). Type `TEXT` is the SQLite default and is used for dates (ISO 8601 strings), enums, and most string fields. `INTEGER` columns with default 0 or 1 are boolean flags in practice. `REAL` is used for money and decimal quantities.

---

### `users`

| Col | Type | Notes |
|---|---|---|
| `username` | TEXT | PK |
| `password_hash` | TEXT | NOT NULL — PBKDF2-HMAC-SHA256, 200k iterations, base64(salt+hash) |
| `full_name` | TEXT |  |
| `role` | TEXT | default=`operator` — also: `admin` |
| `is_active` | INTEGER | default=1 — soft-disable users without losing audit linkage |
| `must_change_password` | INTEGER | default=1 — forces /change-password redirect on first login |
| `created_at` | TEXT |  |
| `last_login` | TEXT |  |

---

### `bills`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `bill_no` | TEXT | NOT NULL — human-readable, e.g. JL-0008 |
| `bill_date` | TEXT |  |
| `recipient_name` | TEXT | The consignor / paying party |
| `recipient_address` | TEXT |  |
| `recipient_gstin` | TEXT |  |
| `state_code` | TEXT | 2-digit GST state code (e.g. 09 = UP) |
| `trip_type` | TEXT | `One Way` / `Two Way` |
| `vehicle_no` | TEXT |  |
| `freight_type` | TEXT | e.g. `A1/A4` — consignor's internal freight code |
| `delivery_month` | TEXT | `MMM/YY`, displayed in bill footer |
| `client_name` | TEXT | Display-only override for tax-footer text |
| `total_amount` | REAL | default=0 — computed sum of deliveries |
| `deliveries` | TEXT | default=`[]` — JSON array of delivery line items |
| `created_at` | TEXT |  |
| `ledger_entry_id` | INTEGER | FK → ledger_entries.id (for single-LR bills) |
| `client_paid` | INTEGER | default=0 |
| `client_paid_date` | TEXT |  |
| `client_paid_amount` | REAL |  |
| `client_paid_mode` | TEXT | `Cash` / `Bank` / `UPI` / `Cheque` |
| `client_paid_reference` | TEXT |  |

**`deliveries` JSON shape (per line item)**:

```json
{
  "gr_no": "12571",
  "outward_no": "880207639",
  "outward_date": "2026-05-03",
  "inward_no": "",
  "inward_date": "",
  "location": "DIBIYAPUR",
  "consignee": "VAIBHAV LAXMI ENTERPRISES",
  "delivery_qty": 1100,
  "converted_case": 1100,
  "inward_qty": "",
  "empty_qty": "",
  "weight": 20110.5,
  "freight_rate": 6233.82,
  "overload": 0,
  "toll_tax": 0,
  "excess_km": 0,
  "detention": 0,
  "unloading": 0,
  "value_of_supply": 6234
}
```

---

### `challans`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `lr_no` | TEXT | The LR / GR number — printed pre-numbered on the challan slip |
| `challan_date` | TEXT |  |
| `consignor_name` | TEXT | Who hires JL — typically Shri Shiv Shakti |
| `consignor_address` | TEXT |  |
| `consignee_name` | TEXT | Destination party |
| `consignee_address` | TEXT |  |
| `from_city_state` | TEXT |  |
| `to_city_state` | TEXT |  |
| `invoice_no` | TEXT | Consignor's invoice number, appears on PoD middle slash |
| `invoice_date` | TEXT |  |
| `consignment_value` | REAL |  |
| `gst_number` | TEXT |  |
| `no_of_articles` | TEXT | Free text — can be "610 nos" or "1 lot" |
| `description` | TEXT |  |
| `value_of_goods` | REAL |  |
| `weight_kg` | REAL |  |
| `del_no` | TEXT | JL's outward delivery number — usually = consignor PoD Doc No. |
| `shipment_no` | TEXT | Optional alt identifier |
| `cost_no` | TEXT | Optional alt identifier |
| `seal_no` | TEXT | Tamper seal applied at dispatch |
| `driver_name` | TEXT |  |
| `driver_mobile` | TEXT |  |
| `truck_no` | TEXT | Normalised: uppercase, no spaces |
| `gate_in_time` | TEXT |  |
| `gate_out_time` | TEXT |  |
| `lane_transit_time` | TEXT |  |
| `expected_arrival` | TEXT |  |
| `source_image` | TEXT | Relative path under uploads/, the photo we extracted |
| `raw_extraction` | TEXT | Full Gemini JSON response (for forensics) |
| `confidence_json` | TEXT | `{field: 'low'\|'medium'}` for fields the AI flagged |
| `status` | TEXT | default=`open` — also: `draft`, `pod_received`, `billed` |
| `notes` | TEXT |  |
| `created_at` | TEXT |  |
| `updated_at` | TEXT |  |
| `ledger_entry_id` | INTEGER | FK → ledger_entries.id (cross-stage Phase D link) |
| `pod_doc_no` | TEXT | What the buyer's PoD slip Doc No. says — should match `del_no` |

---

### `ledger_entries`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `challan_id` | INTEGER | FK → challans.id (nullable for manually-entered) |
| `entry_date` | TEXT |  |
| `gr_no` | TEXT | = challans.lr_no in practice |
| `vehicle_no` | TEXT |  |
| `station` | TEXT | Destination |
| `shipment_no` | TEXT | Often = challans.invoice_no |
| `trip_type` | TEXT | default=`One Way` |
| `mt_qty` | REAL | Tonnage (1 mt = 1000 kg) |
| `freight` | REAL | default=0 — what JL earns for this trip |
| `advance_cash` | REAL | default=0 — cash given to driver |
| `advance_account` | REAL | default=0 — account-transfer advance |
| `diesel` | REAL | default=0 — diesel cost (charged to truck) |
| `diesel_vendor_id` | INTEGER | FK → diesel_vendors.id |
| `transporter_id` | INTEGER | FK → transporters.id (null = family-owned truck) |
| `pod_received` | INTEGER | default=0 |
| `pod_date` | TEXT |  |
| `pod_image` | TEXT | Path under uploads/pods/ |
| `paid` | INTEGER | default=0 — driver/transporter settled? |
| `paid_date` | TEXT |  |
| `paid_mode` | TEXT |  |
| `paid_amount` | REAL |  |
| `paid_reference` | TEXT |  |
| `remarks` | TEXT |  |
| `created_at` | TEXT |  |
| `updated_at` | TEXT |  |
| `bill_id` | INTEGER | FK → bills.id (Phase D link) |
| `weight_kg` | REAL | Optional ledger-side weight, for cross-verification with challan |

**Computed**: `balance = freight − advance_cash − advance_account − diesel` (computed in Python, not stored)

---

### `payments`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `party_type` | TEXT | NOT NULL — `client` / `transporter` / `diesel_vendor` |
| `party_key` | TEXT | NOT NULL — recipient name for `client`, id for others |
| `payment_date` | TEXT | NOT NULL |
| `amount` | REAL | NOT NULL — always positive; direction implied by `party_type` |
| `mode` | TEXT | `Cash` / `Bank` / `UPI` / `Cheque` |
| `reference` | TEXT |  |
| `notes` | TEXT |  |
| `source` | TEXT | default=`manual` — also: `migrated` |
| `created_at` | TEXT |  |
| `created_by` | TEXT |  |

---

### `audit_log`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `occurred_at` | TEXT | NOT NULL |
| `user_name` | TEXT | From current_user() session |
| `action` | TEXT | `create` / `update` / `delete` / `pod_mark` / `bulk_pod` / `reset_password` / … |
| `entity` | TEXT | `bill` / `challan` / `ledger_entry` / `payment` / `user` |
| `entity_id` | INTEGER |  |
| `summary` | TEXT | Human-readable one-liner |
| `changes` | TEXT | JSON: `{field: [old, new], ...}` |

**Indexes**: `idx_audit_entity` on `(entity, entity_id)`; `idx_audit_when` on `occurred_at DESC`.

---

### `transporters`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `name` | TEXT | NOT NULL, UNIQUE |
| `mobile` | TEXT |  |
| `bank_details` | TEXT |  |
| `notes` | TEXT |  |
| `created_at` | TEXT |  |
| `updated_at` | TEXT |  |

---

### `diesel_vendors`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `name` | TEXT | NOT NULL |
| `location` | TEXT |  |
| `notes` | TEXT |  |
| `created_at` | TEXT |  |
| `updated_at` | TEXT |  |

---

### `recipients`

| Col | Type | Notes |
|---|---|---|
| `name` | TEXT | PK |
| `address` | TEXT |  |
| `gstin` | TEXT |  |
| `state_code` | TEXT |  |
| `updated_at` | TEXT |  |
| `freight_rate` | REAL | Last-billed rate cached for fallback when rate list misses |

---

### `vehicles`

| Col | Type | Notes |
|---|---|---|
| `vehicle_no` | TEXT | PK — normalised: uppercase, no spaces |
| `updated_at` | TEXT |  |
| `transporter_id` | INTEGER | FK → transporters.id (which owner does this truck belong to) |

---

### `drivers`

| Col | Type | Notes |
|---|---|---|
| `mobile` | TEXT | PK |
| `name` | TEXT |  |
| `updated_at` | TEXT |  |

---

### `freight_rates` (the rate list)

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `customer_name` | TEXT | The **consignee** (destination party) — NOT the bill recipient |
| `party_code` | TEXT |  |
| `location` | TEXT | Destination town/city |
| `dist_twy_km` | INTEGER | Two-way distance |
| `dist_owy_km` | INTEGER | One-way distance |
| `lp_owy` | REAL | LP truck, one-way rate |
| `lp_twy` | REAL | LP truck, two-way rate |
| `trolla_owy` | REAL | Trolla truck, one-way rate |
| `trolla_twy` | REAL | Trolla truck, two-way rate |
| `updated_at` | TEXT |  |

Uniqueness: `UNIQUE(customer_name, location)` — one consignee can have multiple destinations.

---

### `extractions`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `created_at` | TEXT |  |
| `mode` | TEXT | `combine` / `split` — how to assemble multi-photo extractions |
| `status` | TEXT | `pending` / `extracted` / `reviewed` / `used` |
| `note` | TEXT |  |

---

### `extracted_invoices`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `extraction_id` | INTEGER | FK → extractions.id |
| `file_name` | TEXT | Path under uploads/ |
| `seq` | INTEGER | Order in batch |
| `raw_json` | TEXT | Gemini's raw output |
| `edited_json` | TEXT | After user review |
| `error` | TEXT |  |

---

### `ledger_extractions`

| Col | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `source_image` | TEXT |  |
| `page_date` | TEXT | The date written on the ledger page header |
| `raw_json` | TEXT |  |
| `edited_json` | TEXT |  |
| `status` | TEXT | default=`pending` |
| `created_at` | TEXT |  |

---

### `settings` (singleton-ish)

| Col | Type | Notes |
|---|---|---|
| `key` | TEXT | PK |
| `value` | TEXT |  |

**Keys currently in use**:

- `next_bill_number` — auto-incrementing counter for bill numbering
- `next_lr_number` — auto-incrementing LR counter
- `pod_overdue_days` — default 10
- `default_consignor_name`, `default_consignor_address`, `default_consignor_gstin`, `default_consignor_state` — pre-fill new bills with the family's main consignor
- `client_name` — display name for the tax footer
- `vehicle_type` — `LP` / `Trolla` default
- `freight_type` — `A1/A4` default
- `clients` — JSON array of allowed client names (for the picker)
- `recipient_name_consignor_fix` — migration flag, ignore in queries

---

## Indexes summary

```sql
CREATE INDEX idx_audit_entity     ON audit_log(entity, entity_id);
CREATE INDEX idx_audit_when       ON audit_log(occurred_at DESC);
CREATE INDEX idx_bills_date       ON bills(bill_date DESC);
CREATE INDEX idx_bills_recipient  ON bills(recipient_name);
CREATE INDEX idx_bills_paid       ON bills(client_paid);
CREATE INDEX idx_ledger_date      ON ledger_entries(entry_date DESC);
CREATE INDEX idx_ledger_pod       ON ledger_entries(pod_received, bill_id);
CREATE INDEX idx_ledger_vehicle   ON ledger_entries(vehicle_no);
CREATE INDEX idx_ledger_transp    ON ledger_entries(transporter_id);
CREATE INDEX idx_challans_lr      ON challans(lr_no);
CREATE INDEX idx_challans_status  ON challans(status);
CREATE INDEX idx_rates_customer   ON freight_rates(customer_name);
```

These were chosen based on observed query patterns. The CTO should rerun `EXPLAIN QUERY PLAN` after every major schema change to confirm new queries hit indexes.
