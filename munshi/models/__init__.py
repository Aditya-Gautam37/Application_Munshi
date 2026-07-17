"""ORM models, one module per table group — all mapped onto the schema
app.py's init_db() already owns (see base.py). Importing this package
registers every model on Base's metadata, which repositories rely on for
querying; it does not create or alter any table.
"""
from .base import Base
from .user import User
from .settings import Setting
from .bill import Bill
from .challan import Challan
from .ledger import LedgerEntry
from .payment import Payment
from .extraction import Extraction, ExtractedInvoice, LedgerExtraction
from .master_data import Recipient, Vehicle, Driver, Transporter, DieselVendor, FreightRate
from .license import LicenseState, GoogleDriveState
from .audit import AuditLog

__all__ = [
    'Base', 'User', 'Setting', 'Bill', 'Challan', 'LedgerEntry', 'Payment',
    'Extraction', 'ExtractedInvoice', 'LedgerExtraction',
    'Recipient', 'Vehicle', 'Driver', 'Transporter', 'DieselVendor', 'FreightRate',
    'LicenseState', 'GoogleDriveState', 'AuditLog',
]
