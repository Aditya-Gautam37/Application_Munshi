"""Recycle Bin (soft-delete / restore / purge) — Postgres port of app.py's
generic `_RECYCLE`-table-driven routes. SQLite moves a row with
`INSERT INTO x_archive SELECT * FROM x WHERE id=?`; there's no equivalent
single-statement column-agnostic copy in the ORM, so these three functions
copy field-by-field between a live model and its hand-mirrored archive
model (see munshi/pg/models.py's "Recycle Bin archive tables" section),
driven by a config dict identical in shape to app.py's `_RECYCLE`.

One generic implementation reused for all four entity types, same as the
SQLite version's one generic route body driven by a config dict.
"""
from sqlalchemy import update


def _shared_columns(src_cls, dst_cls):
    dst_names = {c.name for c in dst_cls.__table__.columns}
    return [c.name for c in src_cls.__table__.columns if c.name in dst_names]


def archive_and_delete(session, organization_id, model_cls, archive_cls, row_id):
    """Moves the live row into its archive table and deletes the live row.
    Returns the archived row, or None if it wasn't found (or belongs to a
    different org). Caller commits."""
    row = session.get(model_cls, row_id)
    if row is None or str(row.organization_id) != str(organization_id):
        return None
    cols = _shared_columns(model_cls, archive_cls)
    archived = archive_cls(**{c: getattr(row, c) for c in cols})
    session.add(archived)
    session.delete(row)
    session.flush()
    return archived


def restore(session, organization_id, model_cls, archive_cls, row_id):
    """Moves an archived row back to the live table with its original id
    (so FK links re-validate automatically). Returns (row, error) where
    error is None on success, or one of 'not_found' / 'already_exists'."""
    archived = session.get(archive_cls, row_id)
    if archived is None or str(archived.organization_id) != str(organization_id):
        return None, 'not_found'
    if session.get(model_cls, row_id) is not None:
        return None, 'already_exists'
    cols = _shared_columns(archive_cls, model_cls)
    restored = model_cls(**{c: getattr(archived, c) for c in cols})
    session.add(restored)
    session.delete(archived)
    session.flush()
    return restored, None


def purge(session, organization_id, archive_cls, row_id, null_fk_specs=()):
    """Permanently deletes an archived row. `null_fk_specs` is a list of
    (model_cls, column_name) — the now-permanently-broken FK links pointing
    at this id get nulled so the freed records can be reused (e.g. ledger
    trips go back to "ready to bill"). Returns False if not found."""
    archived = session.get(archive_cls, row_id)
    if archived is None or str(archived.organization_id) != str(organization_id):
        return False
    for model_cls, col_name in null_fk_specs:
        column = getattr(model_cls, col_name)
        session.execute(
            update(model_cls)
            .where(column == row_id, model_cls.organization_id == organization_id)
            .values(**{col_name: None})
        )
    session.delete(archived)
    session.flush()
    return True
