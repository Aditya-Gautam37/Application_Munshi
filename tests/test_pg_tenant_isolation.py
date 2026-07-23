"""Gate A — proves the multi-tenant RLS plumbing (munshi/pg/database.py's
set_tenant_context() + the policies applied by sql/001_baseline_schema.sql)
actually isolates tenants, on both reads and writes, against the live
Supabase project. Automates what was previously only a human's manual
finding (the "empirically verified 2026-07-17" comment in
munshi/pg/database.py:66-73) into a re-runnable regression test.

Everything this migration builds on top of RLS is only as safe as this file
staying green. Skips (not fails) when DATABASE_URL isn't set — see
tests/conftest.py's pg_session fixture.
"""
import uuid

from sqlalchemy import delete, text

from munshi.pg.models import Organization
from munshi.pg.services.organization_service import create_organization
from munshi.pg.services.transporter_service import create_transporter, list_transporters


def test_tenant_isolation_blocks_cross_org_read_and_write(pg_session):
    from munshi.pg import database as pg_database

    session = pg_session
    suffix = uuid.uuid4().hex[:8]

    # Orgs are created under the default (bypass-RLS) role — `organizations`
    # has only a SELECT policy, no INSERT policy, by design (see
    # organization_service.py's docstring).
    org_a = create_organization(session, name=f'Test Org A {suffix}')
    org_b = create_organization(session, name=f'Test Org B {suffix}')
    session.commit()
    org_a_id, org_b_id = org_a.id, org_b.id

    try:
        # Under org A's context, create one transporter.
        pg_database.set_tenant_context(session, org_id=org_a_id)
        create_transporter(session, org_a_id, name=f'Transporter A {suffix}')
        session.commit()

        # Under org B's context: org A's transporter must be invisible.
        pg_database.set_tenant_context(session, org_id=org_b_id)
        assert list_transporters(session) == []

        # Under org B's context: inserting a row tagged organization_id=org_a
        # must be rejected by the WITH CHECK clause, not silently allowed.
        raised = None
        try:
            create_transporter(session, org_a_id, name=f'Sneaky {suffix}')
        except Exception as e:  # noqa: BLE001 — asserting on the message below
            raised = e
        finally:
            session.rollback()  # required: the failed INSERT aborts the transaction

        assert raised is not None, 'cross-tenant insert should have been rejected by RLS, but succeeded'
        assert 'row-level security' in str(raised).lower(), (
            f'insert failed, but not for the expected RLS reason: {raised}'
        )

        # Back under org A's context: exactly the one transporter is visible.
        pg_database.set_tenant_context(session, org_id=org_a_id)
        visible = list_transporters(session)
        assert len(visible) == 1
        assert visible[0].name == f'Transporter A {suffix}'
    finally:
        session.rollback()
        session.execute(text('RESET ROLE'))
        session.execute(delete(Organization).where(Organization.id.in_([org_a_id, org_b_id])))
        session.commit()
