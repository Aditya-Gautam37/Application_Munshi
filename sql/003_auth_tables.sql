-- Munshi — Supabase Postgres migration 0003
-- Mirrors munshi/pg/migrations/versions/0003_auth_tables.py.
-- Run once in Supabase SQL Editor, after 001 and 002.
--
-- Non-tenant auth table: this single-business deployment keeps its
-- existing homegrown username+password login (not Supabase Auth), so this
-- table deliberately has NO organization_id column and NO RLS policy —
-- there is no tenant to scope by. See munshi/pg/auth_models.py.
--
-- Login-failure/lockout tracking does NOT get a new table here — it reuses
-- the EXISTING login_failures table from 001_baseline_schema.sql
-- (organization_id, identifier, failed_at), tagged with the one fixed
-- organization id this deployment uses.

create table users (
  username               text primary key,
  password_hash          text not null,
  full_name              text,
  role                   text not null default 'operator',
  is_active              boolean not null default true,
  must_change_password   boolean not null default true,
  created_at             text,
  last_login             text
);
