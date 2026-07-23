"""Organization/membership creation — the two tables RLS itself can't scope
by a pre-existing organization_id, since creating an org is what MINTS that
id in the first place.

`create_organization` deliberately does NOT call set_tenant_context(): the
`organizations` table's only RLS policy is `organizations_member_read`
(SELECT-only, see the baseline migration) — there is no INSERT policy, so an
`authenticated`-role session can never create an org, by design. Org creation
must run under the default bypass-RLS role bound in munshi/pg/database.py
(`postgres`/`service_role`), same as any other trust-the-server operation
(e.g. a signup flow backed by the service-role key).
"""
from munshi.pg.database import set_tenant_context
from munshi.pg.models import Membership, Organization


def create_organization(session, name, **kwargs):
    """kwargs may include any other Organization column (gstin, pan,
    address, state_code, phone, subscription_status). Caller commits."""
    org = Organization(name=name, **kwargs)
    session.add(org)
    session.flush()  # populate org.id (server_default gen_random_uuid()) without committing yet
    return org


def create_membership(session, org_id, user_id, role='admin', full_name=None):
    """Sets tenant context to `org_id` for this call, since `memberships`
    carries the standard ALL-command RLS policy (organization_id =
    current_org_id()) — inserting without it fails the WITH CHECK clause.
    `user_id` is Supabase Auth's own auth.users.id (a UUID), not created
    here."""
    set_tenant_context(session, org_id=org_id, user_id=user_id, role=role)
    membership = Membership(organization_id=org_id, user_id=user_id, role=role, full_name=full_name)
    session.add(membership)
    session.flush()
    return membership
