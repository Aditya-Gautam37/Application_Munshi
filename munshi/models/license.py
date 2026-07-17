"""Maps the two singleton (id=1) config tables: license_state and
google_drive_state (app.py init_db())."""
from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LicenseState(Base):
    __tablename__ = 'license_state'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # CHECK (id = 1) enforced by schema DDL
    license_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)  # active|grace|locked|expired|suspended|not_found|unconfigured
    tier: Mapped[str | None] = mapped_column(Text)
    max_trucks: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[str | None] = mapped_column(Text)
    days_to_expiry: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)


class GoogleDriveState(Base):
    __tablename__ = 'google_drive_state'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # CHECK (id = 1) enforced by schema DDL
    refresh_token: Mapped[str | None] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(Text)
    access_token_expiry: Mapped[str | None] = mapped_column(Text)
    folder_id: Mapped[str | None] = mapped_column(Text)
    folder_name: Mapped[str | None] = mapped_column(Text)
    connected_email: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[str | None] = mapped_column(Text)
    last_sync_status: Mapped[str | None] = mapped_column(Text)
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    last_uploaded_file: Mapped[str | None] = mapped_column(Text)
