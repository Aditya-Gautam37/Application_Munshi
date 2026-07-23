-- Munshi — Supabase Postgres migration 0002
-- Mirrors munshi/pg/migrations/versions/0002_ledger_settlement_fields.py.
-- Run once in Supabase SQL Editor, after 001_baseline_schema.sql.
--
-- Adds the 7 POD-time settlement columns that payment_service's
-- _transporter_charges_net() and ledger_service's ledger_balance() both
-- read — present in the live SQLite app (app.py's _add_column_if_missing())
-- but missing from the original 0001 baseline.

alter table ledger_entries add column shortage   numeric default 0;
alter table ledger_entries add column leakage    numeric default 0;
alter table ledger_entries add column breakage   numeric default 0;
alter table ledger_entries add column unloading  numeric default 0;
alter table ledger_entries add column detention  numeric default 0;
alter table ledger_entries add column toll_tax   numeric default 0;
alter table ledger_entries add column excess_km  numeric default 0;
