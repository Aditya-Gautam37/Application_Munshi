"""Maps the `settings` key/value table (app.py init_db(), CREATE TABLE settings)."""
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Setting(Base):
    __tablename__ = 'settings'

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
