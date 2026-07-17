"""Declarative base for the multi-tenant Postgres schema.

Unlike munshi/models/base.py (which maps onto a schema init_db() owns and
never calls create_all()/Alembic on), THIS Base is the schema authority for
the Supabase database — Alembic's env.py targets this metadata directly, and
`alembic revision --autogenerate` diffs the live DB against it.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
