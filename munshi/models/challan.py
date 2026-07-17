"""Maps the `challans` table (app.py init_db(), CREATE TABLE challans, plus the
Phase D/F columns added via _add_column_if_missing)."""
from sqlalchemy import Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Challan(Base):
    __tablename__ = 'challans'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lr_no: Mapped[str | None] = mapped_column(Text, unique=True)
    challan_date: Mapped[str | None] = mapped_column(Text)
    consignor_name: Mapped[str | None] = mapped_column(Text)
    consignor_address: Mapped[str | None] = mapped_column(Text)
    consignee_name: Mapped[str | None] = mapped_column(Text)
    consignee_address: Mapped[str | None] = mapped_column(Text)
    from_city_state: Mapped[str | None] = mapped_column(Text)
    to_city_state: Mapped[str | None] = mapped_column(Text)
    invoice_no: Mapped[str | None] = mapped_column(Text)
    invoice_date: Mapped[str | None] = mapped_column(Text)
    consignment_value: Mapped[float | None] = mapped_column(Float)
    gst_number: Mapped[str | None] = mapped_column(Text)
    no_of_articles: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    value_of_goods: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    del_no: Mapped[str | None] = mapped_column(Text)
    shipment_no: Mapped[str | None] = mapped_column(Text)
    cost_no: Mapped[str | None] = mapped_column(Text)
    seal_no: Mapped[str | None] = mapped_column(Text)
    driver_name: Mapped[str | None] = mapped_column(Text)
    driver_mobile: Mapped[str | None] = mapped_column(Text)
    truck_no: Mapped[str | None] = mapped_column(Text)
    gate_in_time: Mapped[str | None] = mapped_column(Text)
    gate_out_time: Mapped[str | None] = mapped_column(Text)
    lane_transit_time: Mapped[str | None] = mapped_column(Text)
    expected_arrival: Mapped[str | None] = mapped_column(Text)
    source_image: Mapped[str | None] = mapped_column(Text)
    raw_extraction: Mapped[str | None] = mapped_column(Text)
    confidence_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, default='open')  # open | pod_received | billed
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)

    # Phase D/F — cross-stage links
    ledger_entry_id: Mapped[int | None] = mapped_column(Integer)
    pod_doc_no: Mapped[str | None] = mapped_column(Text)
