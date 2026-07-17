"""Maps the `users` table (app.py init_db(), CREATE TABLE users)."""
from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    __tablename__ = 'users'

    username: Mapped[str] = mapped_column(Text, primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text, default='operator')
    is_active: Mapped[int | None] = mapped_column(Integer, default=1)
    must_change_password: Mapped[int | None] = mapped_column(Integer, default=1)
    created_at: Mapped[str | None] = mapped_column(Text)
    last_login: Mapped[str | None] = mapped_column(Text)
