"""Numbering service tests — proves allocate_number() (munshi/pg/services/
numbering_service.py) is sequential per (org, sequence_name), independent
across sequences/orgs, and — the real payoff — race-free under actual
concurrency via SELECT ... FOR UPDATE row-locking. This is something the old
SQLite scan-and-retry / max-plus-one schemes could never rigorously
guarantee; this test makes it provable.

Skips unless DATABASE_URL is set (see tests/conftest.py's pg_session fixture).
"""
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import delete, text

from munshi.pg.models import Organization
from munshi.pg.services.numbering_service import allocate_number
from munshi.pg.services.organization_service import create_organization


def test_allocate_number_increments_sequentially(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    suffix = uuid.uuid4().hex[:8]
    org = create_organization(session, name=f'Numbering Test {suffix}')
    session.commit()
    org_id = org.id

    try:
        pg_database.set_tenant_context(session, org_id=org_id)
        bill_numbers = [allocate_number(session, org_id, 'bill_no') for _ in range(5)]
        lr_numbers = [allocate_number(session, org_id, 'lr_no') for _ in range(3)]
        session.commit()

        assert bill_numbers == [1, 2, 3, 4, 5]
        assert lr_numbers == [1, 2, 3]  # independent counter, same org
    finally:
        session.rollback()
        session.execute(text('RESET ROLE'))
        session.execute(delete(Organization).where(Organization.id == org_id))
        session.commit()


def test_allocate_number_is_race_free_under_concurrency(pg_session):
    """N threads race to allocate a bill number for the SAME org at the same
    time. Each opens its own thread-local session (scoped_session, pulling
    from the already-bound, thread-safe shared engine — bind() itself is
    NOT called per-thread, that would race-dispose the shared engine out
    from under other threads). SELECT ... FOR UPDATE serializes them on the
    (org, 'bill_no') counter row: assert the results are exactly 1..N with
    zero duplicates and zero gaps."""
    from munshi.pg import database as pg_database

    session = pg_session
    suffix = uuid.uuid4().hex[:8]
    org = create_organization(session, name=f'Numbering Race Test {suffix}')
    session.commit()
    org_id = org.id

    n_threads = 10

    def _allocate_in_own_session():
        thread_session = pg_database.get_session()  # thread-local, shares the already-bound engine
        try:
            pg_database.set_tenant_context(thread_session, org_id=org_id)
            n = allocate_number(thread_session, org_id, 'bill_no')
            thread_session.commit()
            return n
        finally:
            pg_database.remove_session()

    try:
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(_allocate_in_own_session) for _ in range(n_threads)]
            results = [f.result() for f in as_completed(futures)]

        assert sorted(results) == list(range(1, n_threads + 1)), (
            f'expected exactly {list(range(1, n_threads + 1))} with no duplicates/gaps, got {sorted(results)}'
        )
    finally:
        session.rollback()
        session.execute(text('RESET ROLE'))
        session.execute(delete(Organization).where(Organization.id == org_id))
        session.commit()
