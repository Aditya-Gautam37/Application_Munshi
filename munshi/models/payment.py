"""Maps the `payments` table — the single source of truth for AR/AP balances
(app.py init_db(), CREATE TABLE payments). See services/payment_service.py
(added in Phase 5) for the balance-calculation logic that reads this table."""
from sqlalchemy import Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Payment(Base):
    __tablename__ = 'payments'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_type: Mapped[str] = mapped_column(Text, nullable=False)   # client | transporter | diesel_vendor
    party_key: Mapped[str] = mapped_column(Text, nullable=False)    # recipient name, or id as str
    payment_date: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)    # always positive
    mode: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text, default='manual')  # manual | migrated | auto
    created_at: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
