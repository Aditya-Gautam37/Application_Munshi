"""Per-tenant sequential number allocation (bill numbers, LR numbers) —
replaces app.py's two SQLite schemes:
  - `_alloc_bill_no`: max(counter, MAX(existing)+1) + retry-on-IntegrityError,
    self-healing against drift (demo-data loads, restores, manual edits) that
    was only possible because those bypassed the counter directly.
  - `find_unique_lr_no`: linear scan-and-check up to 10,000 candidates, no
    retry-on-collision at any call site — a real, unguarded race in SQLite.

Neither scheme is ported. `NumberSequence` is authoritative from row one in
Postgres — nothing else can insert a Bill/Challan with a number outside this
path, so there's nothing to self-heal against. `SELECT ... FOR UPDATE`
row-locks the (organization_id, sequence_name) counter for the rest of the
transaction, making allocation atomic and race-free by construction; a
second concurrent caller for the SAME org+sequence blocks until the first
commits, then sees the incremented value. Different orgs/sequences never
contend (different PK rows). Formatting (e.g. f'JL-{n:04d}' for bills, plain
str(n) for LR numbers) is the caller's job — this function returns a raw int.

If historical bills/LRs with pre-existing numbers are ever imported into
Postgres, that needs a one-time reconciliation script setting next_value
past the imported max — not a per-call safeguard here.
"""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from munshi.pg.models import NumberSequence


def allocate_number(session, organization_id, sequence_name):
    """Returns the next int in this org's sequence, incrementing it. Caller
    commits (same convention as organization_service/transporter_service)."""
    # Bootstrap: create the counter row on first use for this org+sequence.
    # ON CONFLICT DO NOTHING is itself race-free — if two transactions race
    # to bootstrap the same (org, sequence_name) row, exactly one INSERT
    # wins; the loser proceeds straight to the FOR UPDATE below and blocks
    # on it rather than erroring.
    session.execute(
        pg_insert(NumberSequence)
        .values(organization_id=organization_id, sequence_name=sequence_name, next_value=1)
        .on_conflict_do_nothing(index_elements=['organization_id', 'sequence_name'])
    )

    row = session.execute(
        select(NumberSequence)
        .where(
            NumberSequence.organization_id == organization_id,
            NumberSequence.sequence_name == sequence_name,
        )
        .with_for_update()
    ).scalar_one()

    n = row.next_value
    row.next_value = n + 1
    session.flush()
    return n
