"""Maps the autocomplete/master-data tables: recipients, vehicles, drivers,
transporters, diesel_vendors, freight_rates (app.py init_db())."""
from sqlalchemy import Integer, Text, Float, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Recipient(Base):
    __tablename__ = 'recipients'

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text)
    freight_rate: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Vehicle(Base):
    __tablename__ = 'vehicles'

    vehicle_no: Mapped[str] = mapped_column(Text, primary_key=True)
    updated_at: Mapped[str | None] = mapped_column(Text)
    transporter_id: Mapped[int | None] = mapped_column(Integer)


class Driver(Base):
    __tablename__ = 'drivers'

    mobile: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Transporter(Base):
    __tablename__ = 'transporters'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    mobile: Mapped[str | None] = mapped_column(Text)
    bank_details: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class DieselVendor(Base):
    __tablename__ = 'diesel_vendors'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class FreightRate(Base):
    __tablename__ = 'freight_rates'
    __table_args__ = (UniqueConstraint('customer_name', 'location'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_name: Mapped[str | None] = mapped_column(Text)
    party_code: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    dist_twy_km: Mapped[int | None] = mapped_column(Integer)
    dist_owy_km: Mapped[int | None] = mapped_column(Integer)
    lp_owy: Mapped[float | None] = mapped_column(Float)
    lp_twy: Mapped[float | None] = mapped_column(Float)
    trolla_owy: Mapped[float | None] = mapped_column(Float)
    trolla_twy: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str | None] = mapped_column(Text)
