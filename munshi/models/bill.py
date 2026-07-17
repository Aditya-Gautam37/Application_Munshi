"""Maps the `bills` table — GST invoices, the legal document (app.py init_db(),
CREATE TABLE bills, plus the Phase D/E/F/G columns added via
_add_column_if_missing)."""
from sqlalchemy import Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Bill(Base):
    __tablename__ = 'bills'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_no: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    bill_date: Mapped[str | None] = mapped_column(Text)
    recipient_name: Mapped[str | None] = mapped_column(Text)
    recipient_address: Mapped[str | None] = mapped_column(Text)
    recipient_gstin: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text)
    trip_type: Mapped[str | None] = mapped_column(Text)
    vehicle_no: Mapped[str | None] = mapped_column(Text)
    freight_type: Mapped[str | None] = mapped_column(Text)
    delivery_month: Mapped[str | None] = mapped_column(Text)
    client_name: Mapped[str | None] = mapped_column(Text)
    total_amount: Mapped[float | None] = mapped_column(Float, default=0)
    deliveries: Mapped[str | None] = mapped_column(Text, default='[]')  # JSON blob
    created_at: Mapped[str | None] = mapped_column(Text)

    # Phase D — cross-stage links
    ledger_entry_id: Mapped[int | None] = mapped_column(Integer)

    # Phase E — client payment tracking (superseded by the `payments` table as
    # single source of truth, but the columns remain — see PaymentService)
    client_paid: Mapped[int | None] = mapped_column(Integer, default=0)
    client_paid_date: Mapped[str | None] = mapped_column(Text)
    client_paid_amount: Mapped[float | None] = mapped_column(Float)
    client_paid_mode: Mapped[str | None] = mapped_column(Text)
    client_paid_reference: Mapped[str | None] = mapped_column(Text)

    # Phase G — GST-compliant invoicing
    hsn_sac: Mapped[str | None] = mapped_column(Text, default='996511')
    taxable_value: Mapped[float | None] = mapped_column(Float, default=0)
    reverse_charge: Mapped[int | None] = mapped_column(Integer, default=1)
    place_of_supply: Mapped[str | None] = mapped_column(Text)
    igst_pct: Mapped[float | None] = mapped_column(Float, default=0)
    cgst_pct: Mapped[float | None] = mapped_column(Float, default=0)
    sgst_pct: Mapped[float | None] = mapped_column(Float, default=0)
    igst_amount: Mapped[float | None] = mapped_column(Float, default=0)
    cgst_amount: Mapped[float | None] = mapped_column(Float, default=0)
    sgst_amount: Mapped[float | None] = mapped_column(Float, default=0)
    irn: Mapped[str | None] = mapped_column(Text)
    irn_qr: Mapped[str | None] = mapped_column(Text)
