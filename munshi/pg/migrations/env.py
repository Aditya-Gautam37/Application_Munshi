"""Alembic environment for the Supabase/Postgres multi-tenant schema.

Reads the connection string from the DATABASE_URL env var (Supabase's
"connection string" from Project Settings -> Database, using the
`postgresql+psycopg://` scheme for SQLAlchemy 2.0 + psycopg 3) rather than
from alembic.ini, so no credential ever needs to be written to a tracked
file. Target metadata is munshi.pg.models' Base — `alembic revision
--autogenerate` diffs the live database against these models.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Make `munshi` importable when Alembic is invoked from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from munshi.pg import models  # noqa: E402  (registers all models on Base.metadata)
from munshi.pg import auth_models  # noqa: E402  (non-tenant users/login_failures — see that module's docstring)
from munshi.pg.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Read DATABASE_URL as a plain Python string, NOT via config.set_main_option()
# — that writes into alembic.ini's ConfigParser, which treats `%` as the
# start of an interpolation token. A password containing a URL-encoded `%xx`
# (very common — e.g. `%40` for `@`) then raises
# "invalid interpolation syntax", unrelated to whether the URL is otherwise
# correct. create_engine()/context.configure(url=...) take the raw string
# directly and never go through that interpolation step.
database_url = os.environ.get('DATABASE_URL', '').strip()


def run_migrations_offline():
    """Emit SQL to stdout without a live DB connection (`alembic upgrade
    head --sql`) — useful for reviewing exactly what will run before pointing
    this at the real Supabase project."""
    if not database_url:
        raise RuntimeError('DATABASE_URL is not set.')
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    if not database_url:
        raise RuntimeError(
            'DATABASE_URL is not set. Copy the Supabase Postgres connection '
            'string (Project Settings -> Database -> Connection string, URI '
            'tab) into your environment, e.g.:\n'
            '  postgresql+psycopg://postgres:<password>@<host>:5432/postgres'
        )
    connectable = create_engine(database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
