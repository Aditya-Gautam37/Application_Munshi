"""Maps the `ledger_entries` table (app.py init_db(), CREATE TABLE
ledger_entries, plus the Phase D bill_id / Phase F weight_kg columns)."""
from sqlalchemy import Integer, Text, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    challan_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('challans.id'))
    entry_date: Mapped[str | None] = mapped_column(Text)
    gr_no: Mapped[str | None] = mapped_column(Text)
    vehicle_no: Mapped[str | None] = mapped_column(Text)
    station: Mapped[str | None] = mapped_column(Text)
    shipment_no: Mapped[str | None] = mapped_column(Text)
    trip_type: Mapped[str | None] = mapped_column(Text, default='One Way')
    mt_qty: Mapped[float | None] = mapped_column(Float)
    freight: Mapped[float | None] = mapped_column(Float, default=0)
    advance_cash: Mapped[float | None] = mapped_column(Float, default=0)
    advance_account: Mapped[float | None] = mapped_column(Float, default=0)
    diesel: Mapped[float | None] = mapped_column(Float, default=0)
    diesel_vendor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('diesel_vendors.id'))
    transporter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('transporters.id'))
    pod_received: Mapped[int | None] = mapped_column(Integer, default=0)
    pod_date: Mapped[str | None] = mapped_column(Text)
    pod_image: Mapped[str | None] = mapped_column(Text)
    paid: Mapped[int | None] = mapped_column(Integer, default=0)
    paid_date: Mapped[str | None] = mapped_column(Text)
    paid_mode: Mapped[str | None] = mapped_column(Text)
    paid_amount: Mapped[float | None] = mapped_column(Float)
    paid_reference: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)

    # Phase D/F
    bill_id: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Float)
