"""Shared fixtures for tests that talk to the live Supabase Postgres project
(tests/test_pg_*.py). tests/test_smoke.py never imports munshi.pg and is
unaffected by anything here.
"""
import os

import pytest


@pytest.fixture()
def pg_session():
    """A session bound to DATABASE_URL, torn down (rolled back + removed)
    after the test regardless of outcome. Skips the test entirely if
    DATABASE_URL isn't set, rather than failing — these tests need a live
    Supabase project, not just any Postgres."""
    database_url = os.environ.get('DATABASE_URL', '')
    if not database_url:
        pytest.skip('DATABASE_URL not set — skipping test that needs the live Supabase project')

    from munshi.pg import database as pg_database

    pg_database.bind(database_url)
    session = pg_database.get_session()
    try:
        yield session
    finally:
        session.rollback()
        pg_database.remove_session()
