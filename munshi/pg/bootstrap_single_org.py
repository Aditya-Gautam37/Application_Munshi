"""One-time script: creates the single Organization row this deployment
uses (a single-business Postgres cutover, not multi-tenant SaaS — see
.claude/plans/streamed-giggling-crescent.md). Refuses to run if an
organization already exists, since nothing else stops a second accidental
run from creating a duplicate (no uniqueness constraint on Organization.name).

Usage:
    DATABASE_URL=postgresql+psycopg://... python -m munshi.pg.bootstrap_single_org "Firm Name"

Prints the new organization's id — paste it into Render as
MUNSHI_ORGANIZATION_ID.
"""
import os
import sys

from sqlalchemy import select

from munshi.pg import database as pg_database
from munshi.pg.models import Organization
from munshi.pg.services.organization_service import create_organization


def bootstrap(session, name, **org_kwargs):
    existing = session.execute(select(Organization)).scalars().all()
    if existing:
        raise SystemExit(
            f'An organization already exists ({existing[0].id}, "{existing[0].name}") — '
            f'refusing to create a second one. This deployment supports exactly one.'
        )
    org = create_organization(session, name, **org_kwargs)
    session.commit()
    return org


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python -m munshi.pg.bootstrap_single_org "Firm Name"')
    name = sys.argv[1]

    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        raise SystemExit('DATABASE_URL is not set.')

    pg_database.bind(database_url)
    session = pg_database.get_session()
    try:
        org = bootstrap(session, name)
        print(f'Created organization {org.id} ("{org.name}")')
        print(f'Set MUNSHI_ORGANIZATION_ID={org.id}')
    finally:
        pg_database.remove_session()


if __name__ == '__main__':
    main()
