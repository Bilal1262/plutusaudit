"""
Operational tables — separate from the append-only audit log.

Three tables:
    Invoice         - every invoice processed
    Vendor          - mock vendor master
    JournalEntry    - the GL output of Agent 2 (Accountant)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    upload_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    vendor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    grand_total: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(32), default="processing")
    fraud_tier: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    fraud_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processing_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pipeline_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    journal_entries: Mapped[list["JournalEntry"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    bank_account_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    invoice_id: Mapped[str] = mapped_column(String(36), ForeignKey("invoices.id"))
    gl_account_debit: Mapped[str] = mapped_column(String(128))
    gl_account_credit: Mapped[str] = mapped_column(String(128))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    standard_cited: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    paragraph_cited: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.0)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    deferral_required: Mapped[bool] = mapped_column(Boolean, default=False)
    amortization_schedule: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    invoice: Mapped[Invoice] = relationship(back_populates="journal_entries")
