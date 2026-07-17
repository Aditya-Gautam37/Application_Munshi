"""Multi-tenant Postgres schema (Supabase). Every business table carries an
`organization_id` FK enforced twice over — once here for query/join
correctness, once again by a Postgres RLS policy of identical shape on every
table (see the migration in migrations/versions/, which is the actual source
of truth for what's live in the database; this file is the typed read/write
layer + what Alembic autogenerate diffs against for future changes).

Column-type choices, vs. the SQLite schema these tables replace
(see munshi/models/*.py + app.py's init_db() for the SQLite originals):
  - JSON-as-TEXT columns (deliveries, raw_extraction, confidence_json,
    raw_json, edited_json, changes) -> native JSONB.
  - ISO-TEXT dates -> native Date (calendar dates) or DateTime(timezone=True)
    (event timestamps).
  - INTEGER PRIMARY KEY AUTOINCREMENT -> BigInteger identity column.
  - Natural-key primary keys (recipients.name, vehicles.vehicle_no,
    drivers.mobile) -> surrogate BigInteger id + a per-tenant UNIQUE
    constraint, since the natural key is now only unique WITHIN a tenant.
  - license_state / google_drive_state singleton tables -> NOT ported.
    Subscription status lives on Organization; Google Drive backup is
    dropped in favor of Supabase's managed backups (see migration plan,
    Phase 5).
"""
import uuid

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Organization(Base):
    """One row per transport-business tenant. Replaces the SQLite schema's
    global `settings.supplier_*` keys (firm identity) and `license_state`
    (subscription concept — see subscription_status)."""
    __tablename__ = 'organizations'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(Text, nullable=False)
    gstin: Mapped[str | None] = mapped_column(Text)
    pan: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)

    # Replaces license-server's phone-home kill-switch (see migration plan,
    # Phase 5): a hosted multi-tenant app has full server-side authority, so
    # subscription gating is an ordinary authorization check on this column,
    # updated by a payment-provider webhook — not a separate trust-nothing
    # client-side license server.
    subscription_status: Mapped[str] = mapped_column(Text, nullable=False, server_default='trial')
    subscription_provider_id: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    """Replaces the SQLite `users` table (PK was `username` TEXT, no tenant
    concept). `user_id` is Supabase Auth's own `auth.users.id` — Supabase
    owns credentials entirely; this table only carries org membership + the
    role/profile fields the app needs."""
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('organization_id', 'user_id'),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)  # auth.users.id, not FK'd (auth schema is Supabase-managed)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default='operator')  # admin | operator
    full_name: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='true')
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default='en')  # persisted i18n pref, was session['lang']-only
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class LoginFailure(Base):
    """Org-scoped login lockout (app.py's `login_failures`, munshi/services/
    auth_service.py:44-108, was global — must be tenant-scoped here or one
    org's failed logins could lock out a same-named user in another org)."""
    __tablename__ = 'login_failures'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)  # email/username attempted
    failed_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NumberSequence(Base):
    """Per-tenant counters for bill/LR numbers (replaces app.py's
    `_alloc_bill_no`/`find_unique_lr_no` scan-max-and-retry pattern, which
    was only safe under SQLite's single-writer lock — see migration plan
    Section 2). Allocation: SELECT ... FOR UPDATE this row, then UPDATE
    next_value += 1, inside the same transaction as the insert it's for."""
    __tablename__ = 'number_sequences'

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True)
    sequence_name: Mapped[str] = mapped_column(Text, primary_key=True)  # 'bill_no' | 'lr_no'
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default='1')


class Setting(Base):
    """Per-tenant KV store for whatever doesn't warrant its own column
    (was the global `settings` table; firm-identity keys moved onto
    Organization, next_bill_number moved onto NumberSequence)."""
    __tablename__ = 'settings'

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class Recipient(Base):
    __tablename__ = 'recipients'
    __table_args__ = (UniqueConstraint('organization_id', 'name'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text)
    freight_rate: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class Vehicle(Base):
    __tablename__ = 'vehicles'
    __table_args__ = (UniqueConstraint('organization_id', 'vehicle_no'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    vehicle_no: Mapped[str] = mapped_column(Text, nullable=False)
    transporter_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('transporters.id'))
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class Driver(Base):
    __tablename__ = 'drivers'
    __table_args__ = (UniqueConstraint('organization_id', 'mobile'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    mobile: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class Transporter(Base):
    __tablename__ = 'transporters'
    __table_args__ = (UniqueConstraint('organization_id', 'name'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mobile: Mapped[str | None] = mapped_column(Text)
    bank_details: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class DieselVendor(Base):
    __tablename__ = 'diesel_vendors'
    __table_args__ = (UniqueConstraint('organization_id', 'name'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class FreightRate(Base):
    __tablename__ = 'freight_rates'
    __table_args__ = (UniqueConstraint('organization_id', 'customer_name', 'location'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(Text)
    party_code: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    dist_twy_km: Mapped[int | None] = mapped_column(SmallInteger)
    dist_owy_km: Mapped[int | None] = mapped_column(SmallInteger)
    lp_owy: Mapped[float | None] = mapped_column(Numeric)
    lp_twy: Mapped[float | None] = mapped_column(Numeric)
    trolla_owy: Mapped[float | None] = mapped_column(Numeric)
    trolla_twy: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class Bill(Base):
    """GST invoices — the legal document. See munshi/utils/gst.py's
    compute_gst_split() (ported verbatim) for how the igst/cgst/sgst columns
    are computed, and templates/bill_view.html for the legally-required
    conditional rendering that must be reproduced exactly in the new
    frontend (migration plan risk #2)."""
    __tablename__ = 'bills'
    __table_args__ = (UniqueConstraint('organization_id', 'bill_no'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    bill_no: Mapped[str] = mapped_column(Text, nullable=False)
    bill_date: Mapped[object | None] = mapped_column(Date)
    recipient_name: Mapped[str | None] = mapped_column(Text)
    recipient_address: Mapped[str | None] = mapped_column(Text)
    recipient_gstin: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text)
    trip_type: Mapped[str | None] = mapped_column(Text)
    vehicle_no: Mapped[str | None] = mapped_column(Text)
    freight_type: Mapped[str | None] = mapped_column(Text)
    delivery_month: Mapped[str | None] = mapped_column(Text)
    client_name: Mapped[str | None] = mapped_column(Text)
    total_amount: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    deliveries: Mapped[list | None] = mapped_column(JSONB, server_default='[]')
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ledger_entry_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('ledger_entries.id'))

    # Superseded by `payments` as single source of truth (see PaymentService,
    # Phase 2) — columns kept for display/back-compat only, same as the
    # SQLite original (munshi/models/bill.py).
    client_paid: Mapped[bool] = mapped_column(Boolean, server_default='false')
    client_paid_date: Mapped[object | None] = mapped_column(Date)
    client_paid_amount: Mapped[float | None] = mapped_column(Numeric)
    client_paid_mode: Mapped[str | None] = mapped_column(Text)
    client_paid_reference: Mapped[str | None] = mapped_column(Text)

    hsn_sac: Mapped[str | None] = mapped_column(Text, server_default='996511')
    taxable_value: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    reverse_charge: Mapped[bool] = mapped_column(Boolean, server_default='true')
    place_of_supply: Mapped[str | None] = mapped_column(Text)
    igst_pct: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    cgst_pct: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    sgst_pct: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    igst_amount: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    cgst_amount: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    sgst_amount: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    irn: Mapped[str | None] = mapped_column(Text)
    irn_qr: Mapped[str | None] = mapped_column(Text)


class Extraction(Base):
    __tablename__ = 'extractions'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    mode: Mapped[str | None] = mapped_column(Text)     # combine | split
    status: Mapped[str | None] = mapped_column(Text)   # pending | extracted | reviewed | used | failed
    note: Mapped[str | None] = mapped_column(Text)


class ExtractedInvoice(Base):
    __tablename__ = 'extracted_invoices'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    extraction_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('extractions.id', ondelete='CASCADE'))
    file_name: Mapped[str | None] = mapped_column(Text)  # Supabase Storage object key (was a relative FS path)
    seq: Mapped[int | None] = mapped_column(SmallInteger)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    edited_json: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class LedgerExtraction(Base):
    __tablename__ = 'ledger_extractions'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    source_image: Mapped[str | None] = mapped_column(Text)  # Supabase Storage object key
    page_date: Mapped[object | None] = mapped_column(Date)
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    edited_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(Text, server_default='pending')
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Challan(Base):
    __tablename__ = 'challans'
    __table_args__ = (UniqueConstraint('organization_id', 'lr_no'),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    lr_no: Mapped[str | None] = mapped_column(Text)
    challan_date: Mapped[object | None] = mapped_column(Date)
    consignor_name: Mapped[str | None] = mapped_column(Text)
    consignor_address: Mapped[str | None] = mapped_column(Text)
    consignee_name: Mapped[str | None] = mapped_column(Text)
    consignee_address: Mapped[str | None] = mapped_column(Text)
    from_city_state: Mapped[str | None] = mapped_column(Text)
    to_city_state: Mapped[str | None] = mapped_column(Text)
    invoice_no: Mapped[str | None] = mapped_column(Text)
    invoice_date: Mapped[object | None] = mapped_column(Date)
    consignment_value: Mapped[float | None] = mapped_column(Numeric)
    gst_number: Mapped[str | None] = mapped_column(Text)
    no_of_articles: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    value_of_goods: Mapped[float | None] = mapped_column(Numeric)
    weight_kg: Mapped[float | None] = mapped_column(Numeric)
    del_no: Mapped[str | None] = mapped_column(Text)
    shipment_no: Mapped[str | None] = mapped_column(Text)
    cost_no: Mapped[str | None] = mapped_column(Text)
    seal_no: Mapped[str | None] = mapped_column(Text)
    driver_name: Mapped[str | None] = mapped_column(Text)
    driver_mobile: Mapped[str | None] = mapped_column(Text)
    truck_no: Mapped[str | None] = mapped_column(Text)
    gate_in_time: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    gate_out_time: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    lane_transit_time: Mapped[str | None] = mapped_column(Text)
    expected_arrival: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    source_image: Mapped[str | None] = mapped_column(Text)  # Supabase Storage object key
    raw_extraction: Mapped[dict | None] = mapped_column(JSONB)
    confidence_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(Text, server_default='open')  # open | pod_received | billed
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))

    ledger_entry_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('ledger_entries.id'))
    pod_doc_no: Mapped[str | None] = mapped_column(Text)


class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    challan_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('challans.id'))
    entry_date: Mapped[object | None] = mapped_column(Date)
    gr_no: Mapped[str | None] = mapped_column(Text)
    vehicle_no: Mapped[str | None] = mapped_column(Text)
    station: Mapped[str | None] = mapped_column(Text)
    shipment_no: Mapped[str | None] = mapped_column(Text)
    trip_type: Mapped[str | None] = mapped_column(Text, server_default='One Way')
    mt_qty: Mapped[float | None] = mapped_column(Numeric)
    freight: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    advance_cash: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    advance_account: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    diesel: Mapped[float | None] = mapped_column(Numeric, server_default='0')
    diesel_vendor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('diesel_vendors.id'))
    transporter_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('transporters.id'))
    pod_received: Mapped[bool] = mapped_column(Boolean, server_default='false')
    pod_date: Mapped[object | None] = mapped_column(Date)
    pod_image: Mapped[str | None] = mapped_column(Text)  # Supabase Storage object key
    paid: Mapped[bool] = mapped_column(Boolean, server_default='false')
    paid_date: Mapped[object | None] = mapped_column(Date)
    paid_mode: Mapped[str | None] = mapped_column(Text)
    paid_amount: Mapped[float | None] = mapped_column(Numeric)
    paid_reference: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))

    bill_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('bills.id'))
    weight_kg: Mapped[float | None] = mapped_column(Numeric)


class Payment(Base):
    """The single source of truth for AR/AP balances — see
    get_party_balance() (ported to munshi/pg/services/payment_service.py in
    Phase 2), which sums this table per (organization_id, party_type,
    party_key) and subtracts it from each party type's own "charges" query.
    The `_auto_payment_upsert`/`_auto_payment_remove` idempotent-mirroring
    convention from app.py:1094-1116 (legacy `paid` flags -> a `payments` row
    tagged source='auto', reference='auto-paid:...') must be preserved
    exactly — see migration plan risk #1."""
    __tablename__ = 'payments'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    party_type: Mapped[str] = mapped_column(Text, nullable=False)   # client | transporter | diesel_vendor
    party_key: Mapped[str] = mapped_column(Text, nullable=False)    # recipient name, or id as str
    payment_date: Mapped[object] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric, nullable=False)  # always positive
    mode: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text, server_default='manual')  # manual | migrated | auto
    created_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = 'audit_log'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    user_name: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    entity: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    summary: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict | None] = mapped_column(JSONB)
