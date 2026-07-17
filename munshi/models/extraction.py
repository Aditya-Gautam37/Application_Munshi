"""Maps the AI-extraction tables: `extractions` / `extracted_invoices` (bill
photos) and `ledger_extractions` (ledger-page photos). Challan extraction
reuses the `challans` table directly (raw_extraction/confidence_json columns
on Challan itself), so there's no separate model for it here."""
from sqlalchemy import Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Extraction(Base):
    __tablename__ = 'extractions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)      # 'combine' | 'split'
    status: Mapped[str | None] = mapped_column(Text)    # 'pending' | 'extracted' | 'reviewed' | 'used' | 'failed'
    note: Mapped[str | None] = mapped_column(Text)


class ExtractedInvoice(Base):
    __tablename__ = 'extracted_invoices'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    extraction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('extractions.id'))
    file_name: Mapped[str | None] = mapped_column(Text)   # relative path under uploads/
    seq: Mapped[int | None] = mapped_column(Integer)      # order uploaded
    raw_json: Mapped[str | None] = mapped_column(Text)    # full Gemini response JSON
    edited_json: Mapped[str | None] = mapped_column(Text)  # after user edits (null until saved)
    error: Mapped[str | None] = mapped_column(Text)


class LedgerExtraction(Base):
    __tablename__ = 'ledger_extractions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_image: Mapped[str | None] = mapped_column(Text)
    page_date: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str | None] = mapped_column(Text)
    edited_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, default='pending')
    created_at: Mapped[str | None] = mapped_column(Text)
