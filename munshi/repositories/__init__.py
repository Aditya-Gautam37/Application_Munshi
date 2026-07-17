"""Repositories: pure data access via SQLAlchemy sessions. No business rules —
those live in services/. Each repository function opens and closes its own
session via database.engine.get_session(), matching the existing per-call
connection lifecycle of legacy.get_db() rather than introducing a new
long-lived-session pattern the rest of the app doesn't use yet.
"""
