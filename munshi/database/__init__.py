"""Database layer: legacy raw-sqlite3 connection helpers (legacy.py) and the
SQLAlchemy engine used by migrated domains going forward (engine.py). Both
point at the same physical SQLite file — see engine.py's module docstring for
why that's safe.
"""
