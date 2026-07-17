"""Shared declarative base for every ORM model.

These models map onto the schema app.py's init_db() already creates and
migrates via raw SQL — they are a typed reading/writing layer on top of an
existing, already-owned schema, not a schema-authoring tool. Nothing here
ever calls Base.metadata.create_all(); init_db() remains the schema authority
for both fresh installs and upgrading an existing customer's bills.db.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
