-- Munshi — Supabase Postgres baseline schema
-- Mirrors munshi/pg/migrations/versions/0001_baseline.py table-for-table.
-- Run this once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run.
--
-- Multi-tenant design: every business table carries organization_id, and
-- Row Level Security restricts every query to the caller's own org via
-- current_org_id() (reads the `org_id` claim off the caller's Supabase JWT).
-- A table with RLS enabled and no matching policy denies ALL rows by
-- default (fails closed) — every tenant table below gets its policy applied
-- in the loop at the bottom of this file.

create extension if not exists pgcrypto;

-- Reads the `org_id` custom claim that a Supabase Auth Hook injects into
-- every JWT at token-mint time. nullif() guards against '' turning into an
-- invalid ''::jsonb cast once a GUC has been set at all in the session.
create or replace function current_org_id() returns uuid
language sql stable
as $$
  select nullif(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'org_id',
    ''
  )::uuid
$$;

-- ── organizations ────────────────────────────────────────────────────────────
-- One row per tenant firm. Replaces settings.supplier_* + the desktop app's
-- per-install identity.
create table organizations (
  id                        uuid primary key default gen_random_uuid(),
  name                      text not null,
  gstin                     text,
  pan                       text,
  address                   text,
  state_code                text,
  phone                     text,
  subscription_status       text not null default 'trial',
  subscription_provider_id  text,
  created_at                timestamptz default now()
);

alter table organizations enable row level security;
create policy organizations_member_read on organizations
  for select
  using (id = current_org_id());

-- ── memberships ───────────────────────────────────────────────────────────────
-- Join table: a Supabase auth.users.id belongs to one organization with a role.
-- Replaces the old `users` table (admin | operator).
create table memberships (
  id                     uuid primary key default gen_random_uuid(),
  organization_id        uuid not null references organizations(id) on delete cascade,
  user_id                uuid not null,
  role                   text not null default 'operator',
  full_name              text,
  is_active              boolean not null default true,
  must_change_password   boolean not null default false,
  language               text not null default 'en',
  created_at             timestamptz default now(),
  last_login             timestamptz,
  unique (organization_id, user_id)
);

-- ── login_failures ───────────────────────────────────────────────────────────
create table login_failures (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  identifier       text not null,
  failed_at        timestamptz not null default now()
);
create index ix_login_failures_org_identifier on login_failures (organization_id, identifier);

-- ── number_sequences ─────────────────────────────────────────────────────────
-- Per-tenant counters (e.g. bill numbers), allocated via SELECT ... FOR UPDATE
-- to replace SQLite's scan-max-and-retry pattern with a real row lock.
create table number_sequences (
  organization_id  uuid not null references organizations(id) on delete cascade,
  sequence_name    text not null,
  next_value       bigint not null default 1,
  primary key (organization_id, sequence_name)
);

-- ── settings ─────────────────────────────────────────────────────────────────
create table settings (
  organization_id  uuid not null references organizations(id) on delete cascade,
  key              text not null,
  value            text,
  primary key (organization_id, key)
);

-- ── recipients ───────────────────────────────────────────────────────────────
create table recipients (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  name             text not null,
  address          text,
  gstin            text,
  state_code       text,
  freight_rate     numeric,
  updated_at       timestamptz,
  unique (organization_id, name)
);

-- ── transporters ─────────────────────────────────────────────────────────────
create table transporters (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  name             text not null,
  mobile           text,
  bank_details     text,
  notes            text,
  created_at       timestamptz default now(),
  updated_at       timestamptz,
  unique (organization_id, name)
);

-- ── diesel_vendors ───────────────────────────────────────────────────────────
create table diesel_vendors (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  name             text not null,
  location         text,
  notes            text,
  created_at       timestamptz default now(),
  updated_at       timestamptz,
  unique (organization_id, name)
);

-- ── vehicles ─────────────────────────────────────────────────────────────────
create table vehicles (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  vehicle_no       text not null,
  transporter_id   bigint references transporters(id),
  updated_at       timestamptz,
  unique (organization_id, vehicle_no)
);

-- ── drivers ──────────────────────────────────────────────────────────────────
create table drivers (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  mobile           text not null,
  name             text,
  updated_at       timestamptz,
  unique (organization_id, mobile)
);

-- ── freight_rates ────────────────────────────────────────────────────────────
create table freight_rates (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  customer_name    text,
  party_code       text,
  location         text,
  dist_twy_km      smallint,
  dist_owy_km      smallint,
  lp_owy           numeric,
  lp_twy           numeric,
  trolla_owy       numeric,
  trolla_twy       numeric,
  updated_at       timestamptz,
  unique (organization_id, customer_name, location)
);

-- ── bills ────────────────────────────────────────────────────────────────────
-- ledger_entry_id's FK is added after ledger_entries exists (circular ref).
create table bills (
  id                     bigserial primary key,
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
  total_amount           numeric default 0,
  deliveries             jsonb default '[]',
  created_at             timestamptz default now(),
  ledger_entry_id        bigint,
  client_paid            boolean default false,
  client_paid_date       date,
  client_paid_amount     numeric,
  client_paid_mode       text,
  client_paid_reference  text,
  hsn_sac                text default '996511',
  taxable_value          numeric default 0,
  reverse_charge         boolean default true,
  place_of_supply        text,
  igst_pct               numeric default 0,
  cgst_pct               numeric default 0,
  sgst_pct               numeric default 0,
  igst_amount            numeric default 0,
  cgst_amount            numeric default 0,
  sgst_amount            numeric default 0,
  irn                    text,
  irn_qr                 text,
  unique (organization_id, bill_no)
);

-- ── extractions ──────────────────────────────────────────────────────────────
-- One row per AI photo-extraction batch job (challan/bill/ledger-page OCR).
create table extractions (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  created_at       timestamptz default now(),
  mode             text,
  status           text,
  note             text
);

-- ── extracted_invoices ───────────────────────────────────────────────────────
create table extracted_invoices (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  extraction_id    bigint references extractions(id) on delete cascade,
  file_name        text,
  seq              smallint,
  raw_json         jsonb,
  edited_json      jsonb,
  error            text
);

-- ── ledger_extractions ───────────────────────────────────────────────────────
create table ledger_extractions (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  source_image     text,
  page_date        date,
  raw_json         jsonb,
  edited_json      jsonb,
  status           text default 'pending',
  created_at       timestamptz default now()
);

-- ── challans ─────────────────────────────────────────────────────────────────
-- ledger_entry_id's FK is added after ledger_entries exists (circular ref).
create table challans (
  id                    bigserial primary key,
  organization_id       uuid not null references organizations(id) on delete cascade,
  lr_no                 text,
  challan_date          date,
  consignor_name        text,
  consignor_address     text,
  consignee_name        text,
  consignee_address     text,
  from_city_state       text,
  to_city_state         text,
  invoice_no            text,
  invoice_date          date,
  consignment_value     numeric,
  gst_number            text,
  no_of_articles        text,
  description           text,
  value_of_goods        numeric,
  weight_kg             numeric,
  del_no                text,
  shipment_no           text,
  cost_no               text,
  seal_no               text,
  driver_name           text,
  driver_mobile         text,
  truck_no              text,
  gate_in_time          timestamptz,
  gate_out_time         timestamptz,
  lane_transit_time     text,
  expected_arrival      timestamptz,
  source_image          text,
  raw_extraction        jsonb,
  confidence_json       jsonb,
  status                text default 'open',
  notes                 text,
  created_at            timestamptz default now(),
  updated_at            timestamptz,
  ledger_entry_id       bigint,
  pod_doc_no            text,
  unique (organization_id, lr_no)
);

-- ── ledger_entries ───────────────────────────────────────────────────────────
create table ledger_entries (
  id                  bigserial primary key,
  organization_id     uuid not null references organizations(id) on delete cascade,
  challan_id          bigint references challans(id),
  entry_date          date,
  gr_no               text,
  vehicle_no          text,
  station             text,
  shipment_no         text,
  trip_type           text default 'One Way',
  mt_qty              numeric,
  freight             numeric default 0,
  advance_cash        numeric default 0,
  advance_account     numeric default 0,
  diesel              numeric default 0,
  diesel_vendor_id    bigint references diesel_vendors(id),
  transporter_id      bigint references transporters(id),
  pod_received        boolean default false,
  pod_date            date,
  pod_image           text,
  paid                boolean default false,
  paid_date           date,
  paid_mode           text,
  paid_amount         numeric,
  paid_reference      text,
  remarks             text,
  created_at          timestamptz default now(),
  updated_at          timestamptz,
  bill_id             bigint references bills(id),
  weight_kg           numeric
);

-- Circular FKs, added now that both sides exist.
alter table bills add constraint fk_bills_ledger_entry_id
  foreign key (ledger_entry_id) references ledger_entries(id);
alter table challans add constraint fk_challans_ledger_entry_id
  foreign key (ledger_entry_id) references ledger_entries(id);

-- ── payments ─────────────────────────────────────────────────────────────────
-- Single source of truth for who-owes-whom (get_party_balance() reads only
-- this table — see CLAUDE.md "handle with extra care").
create table payments (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  party_type       text not null,
  party_key        text not null,
  payment_date     date not null,
  amount           numeric not null,
  mode             text,
  reference        text,
  notes            text,
  source           text default 'manual',
  created_at       timestamptz default now(),
  created_by       text
);
create index ix_payments_org_party on payments (organization_id, party_type, party_key);
create index ix_payments_org_date on payments (organization_id, payment_date);

-- ── audit_log ────────────────────────────────────────────────────────────────
create table audit_log (
  id               bigserial primary key,
  organization_id  uuid not null references organizations(id) on delete cascade,
  occurred_at      timestamptz not null default now(),
  user_name        text,
  action           text,
  entity           text,
  entity_id        bigint,
  summary          text,
  changes          jsonb
);
create index ix_audit_log_org_entity on audit_log (organization_id, entity, entity_id);
create index ix_audit_log_org_occurred on audit_log (organization_id, occurred_at);

-- ── Row Level Security ───────────────────────────────────────────────────────
-- Same tenant-isolation policy shape on every table that carries
-- organization_id. A table enabled for RLS with no policy denies all rows
-- (fails closed) — this loop is what actually makes each table readable/
-- writable, scoped to the caller's own org.
do $$
declare
  t text;
begin
  foreach t in array array[
    'memberships', 'login_failures', 'number_sequences', 'settings',
    'recipients', 'vehicles', 'drivers', 'transporters', 'diesel_vendors',
    'freight_rates', 'bills', 'extractions', 'extracted_invoices',
    'ledger_extractions', 'challans', 'ledger_entries', 'payments', 'audit_log'
  ]
  loop
    execute format('alter table %I enable row level security', t);
    execute format(
      'create policy %I on %I for all using (organization_id = current_org_id()) with check (organization_id = current_org_id())',
      t || '_tenant_isolation', t
    );
  end loop;
end $$;
