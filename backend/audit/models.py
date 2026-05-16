"""
Append-only audit log.

The chain is forward-immutable: each row carries the SHA-256 hash of the
previous row, so any tamper anywhere in the table is detectable by replaying
the chain (see backend/audit/chain.py::verify_chain).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AuditEntry(Base):
    __tablename__ = "audit_log"

    entry_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sequence: Mapped[int] = mapped_column(Integer, autoincrement=True, unique=True)

    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    agent_name: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    model_name: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))

    output: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3), nullable=True)
    citations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verifier_votes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    user_id: Mapped[str] = mapped_column(String(64), default="system")
    human_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    invoice_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "timestamp": self.timestamp.isoformat() + "Z"
            if self.timestamp
            else None,
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "model_name": self.model_name,
            "input_hash": self.input_hash,
            "output": self.output,
            "confidence": float(self.confidence) if self.confidence is not None else None,
            "citations": self.citations or [],
            "reasoning": self.reasoning,
            "verifier_votes": self.verifier_votes or [],
            "user_id": self.user_id,
            "human_override": self.human_override,
            "invoice_id": self.invoice_id,
        }
