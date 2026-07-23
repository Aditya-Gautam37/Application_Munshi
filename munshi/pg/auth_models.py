"""Non-tenant auth table — a deliberate exception to models.py's "every
table has organization_id + RLS" rule. Mirrors SQLite's `users` table
exactly (see app.py's init_db()), because this single-business deployment
keeps the existing homegrown login, not Supabase Auth/Membership —
Membership has no password_hash column at all and assumes Supabase Auth
owns credentials entirely, so it cannot hold this app's login data.

No organization_id column exists on this table, so no RLS policy is
possible or applicable — see munshi/pg/migrations/versions/0003_auth_tables.py
for why enable_rls() is not called, and munshi/pg/database.py's
set_tenant_context() docstring for why app.py's own Postgres connection
(running as the bypass-RLS `postgres` role, no per-request JWT in a
single-business deployment) never triggers RLS on any table it touches
anyway — explicit organization_id filtering in the services, not RLS, is
what actually scopes queries here.

Login-failure/lockout tracking does NOT get a new table here — it reuses
the EXISTING `login_failures` table already defined in munshi/pg/models.py
(org-scoped: organization_id, identifier, failed_at) from the earlier
multi-tenant work. Since app.py's connection always runs as the bypass-RLS
role, writing rows there tagged with the single fixed ORG_ID works
correctly without needing a second, duplicate table — see
munshi/pg/services/user_service.py, which imports LoginFailure from
munshi.pg.models, not from this module.
"""
from sqlalchemy import Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    __tablename__ = 'users'

    username: Mapped[str] = mapped_column(Text, primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default='operator')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='true')
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='true')
    # Kept TEXT/ISO-string, not DateTime, to match the SQLite column exactly
    # (app.py writes datetime.now().isoformat() into these).
    created_at: Mapped[str | None] = mapped_column(Text)
    last_login: Mapped[str | None] = mapped_column(Text)
