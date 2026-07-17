"""Munshi's layered application package.

Phase 0 of the enterprise-architecture migration: this package currently holds
configuration, the database engine, ORM models, and pure utilities only. Flask
route/service wiring still lives in the top-level app.py and moves here
domain-by-domain in later phases (see the plan in .claude/plans/ if present, or
TASKS.md item C3 for the original scope this expands on).
"""
