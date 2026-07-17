"""Supabase/Postgres multi-tenant stack — parallel to, and independent of, the
existing SQLite-bound `munshi/database` + `munshi/models` used by the desktop
app. Nothing in here is imported by app.py or the desktop build; this package
only comes alive once a Flask API is built against it (see the migration plan
at .claude/plans/polished-tumbling-reef.md, Phases 0-2).

Kept as a separate `Base`/engine on purpose: the SQLite models exist to read
and write a schema `init_db()` already owns, for a single-tenant install. This
package OWNS a brand new multi-tenant Postgres schema (Alembic-managed) and
must never be pointed at the same database as the SQLite path.
"""
