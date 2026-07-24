-- Munshi — Supabase Postgres migration 0004
-- Mirrors munshi/pg/migrations/versions/0004_challan_fixes_and_archive_tables.py.
-- Run once in Supabase SQL Editor, after 001, 002, 003.
--
-- 1) Two real schema bugs on challans: invoice_source_image/
--    invoice_raw_extraction were modeled but never created; gate_in_time/
--    gate_out_time/expected_arrival were modeled as timestamptz but the AI
--    extraction prompt fills them with free-form text, not real timestamps.
-- 2) Four Recycle Bin archive tables (bills/challans/ledger_entries/
--    payments), hand-mirrored (no dynamic column-sync like SQLite has),
--    no FKs to sibling business tables — only organization_id.

alter table challans add column invoice_source_image text;
alter table challans add column invoice_raw_extraction jsonb;

alter table challans alter column gate_in_time type text using gate_in_time::text;
alter table challans alter column gate_out_time type text using gate_out_time::text;
alter table challans alter column expected_arrival type text using expected_arrival::text;

create table bills_archive (
  id                     bigint primary key,
  organization_id        uuid not null references organizations(id) on delete cascade,
  bill_no                text not null,
  bill_date              date,
  recipient_name         text,
  recipient_address      text,
  recipient_gstin        text,
  state_code             text,
  trip_type              text,
  vehicle_no             text,
  freight_type           text,
  delivery_month         text,
  client_name            text,
  total_amount           numeric,
  deliveries             jsonb,
  created_at             timestamptz,
  ledger_entry_id        bigint,
  client_paid            boolean,
  client_paid_date       date,
  client_paid_amount     numeric,
  client_paid_mode       text,
  client_paid_reference  text,
  hsn_sac                text,
  taxable_value          numeric,
  reverse_charge         boolean,
  place_of_supply        text,
  igst_pct               numeric,
  cgst_pct               numeric,
  sgst_pct               numeric,
  igst_amount            numeric,
  cgst_amount            numeric,
  sgst_amount            numeric,
  irn                    text,
  irn_qr                 text
);

create table challans_archive (
  id                     bigint primary key,
  organization_id        uuid not null references organizations(id) on delete cascade,
  lr_no                  text,
  challan_date           date,
  consignor_name         text,
  consignor_address      text,
  consignee_name         text,
  consignee_address      text,
  from_city_state        text,
  to_city_state          text,
  invoice_no             text,
  invoice_date           date,
  consignment_value      numeric,
  gst_number             text,
  no_of_articles         text,
  description            text,
  value_of_goods         numeric,
  weight_kg              numeric,
  del_no                 text,
  shipment_no            text,
  cost_no                text,
  seal_no                text,
  driver_name            text,
  driver_mobile          text,
  truck_no               text,
  gate_in_time           text,
  gate_out_time          text,
  lane_transit_time      text,
  expected_arrival       text,
  source_image           text,
  raw_extraction         jsonb,
  confidence_json        jsonb,
  status                 text,
  notes                  text,
  created_at             timestamptz,
  updated_at             timestamptz,
  ledger_entry_id        bigint,
  pod_doc_no             text,
  invoice_source_image   text,
  invoice_raw_extraction jsonb
);

create table ledger_entries_archive (
  id                  bigint primary key,
  organization_id     uuid not null references organizations(id) on delete cascade,
  challan_id          bigint,
  entry_date          date,
  gr_no               text,
  vehicle_no          text,
  station             text,
  shipment_no         text,
  trip_type           text,
  mt_qty              numeric,
  freight             numeric,
  advance_cash        numeric,
  advance_account     numeric,
  diesel              numeric,
  diesel_vendor_id    bigint,
  transporter_id      bigint,
  shortage            numeric,
  leakage             numeric,
  breakage            numeric,
  unloading           numeric,
  detention           numeric,
  toll_tax            numeric,
  excess_km           numeric,
  pod_received        boolean,
  pod_date            date,
  pod_image           text,
  paid                boolean,
  paid_date           date,
  paid_mode           text,
  paid_amount         numeric,
  paid_reference      text,
  remarks             text,
  created_at          timestamptz,
  updated_at          timestamptz,
  bill_id             bigint,
  weight_kg           numeric
);

create table payments_archive (
  id               bigint primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  party_type       text not null,
  party_key        text not null,
  payment_date     date not null,
  amount           numeric not null,
  mode             text,
  reference        text,
  notes            text,
  source           text,
  created_at       timestamptz,
  created_by       text
);
