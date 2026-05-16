"""
Hash-chained audit log helpers.

`append_entry()` writes a new entry whose `entry_hash` covers the previous
entry's hash. `verify_chain()` replays the chain to detect any tamper.

The canonical hash payload is `json.dumps(..., sort_keys=True)` so two runs
with identical inputs produce the same hash regardless of dict insertion
order.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.audit.models import AuditEntry

GENESIS_HASH = "0" * 64


# ── helpers ────────────────────────────────────────────────────────────────────
def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))


def hash_input(data: Any) -> str:
    """Public helper: stable SHA-256 of any JSON-serialisable payload."""
    return _sha256(_canonical_json(data))


# ── core API ───────────────────────────────────────────────────────────────────
def append_entry(
    db: Session,
    *,
    agent_name: str,
    model_name: str,
    input_data: Any,
    output_data: Any,
    confidence: float = 0.0,
    citations: Optional[list] = None,
    reasoning: Optional[str] = None,
    verifier_votes: Optional[list] = None,
    agent_version: str = "1.0.0",
    user_id: str = "system",
    invoice_id: Optional[str] = None,
) -> AuditEntry:
    """Compute hash, append entry, return the persisted row."""

    last: Optional[AuditEntry] = (
        db.execute(select(AuditEntry).order_by(AuditEntry.sequence.desc()).limit(1))
        .scalars()
        .first()
    )
    prev_hash = last.entry_hash if last else GENESIS_HASH
    next_sequence = (last.sequence + 1) if (last and last.sequence is not None) else 1

    timestamp = datetime.utcnow()
    input_hash = hash_input(input_data)

    canonical = {
        "agent_name": agent_name,
        "agent_version": agent_version,
        "model_name": model_name,
        "input_hash": input_hash,
        "output": output_data,
        "confidence": round(float(confidence or 0.0), 3),
        "citations": citations or [],
        "reasoning": reasoning or "",
        "verifier_votes": verifier_votes or [],
        "prev_hash": prev_hash,
        "timestamp": timestamp.isoformat() + "Z",
    }
    entry_hash = _sha256(_canonical_json(canonical))

    row = AuditEntry(
        sequence=next_sequence,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        timestamp=timestamp,
        agent_name=agent_name,
        agent_version=agent_version,
        model_name=model_name,
        input_hash=input_hash,
        output=output_data,
        confidence=round(float(confidence or 0.0), 3),
        citations=citations or [],
        reasoning=reasoning or "",
        verifier_votes=verifier_votes or [],
        user_id=user_id,
        invoice_id=invoice_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def verify_chain(db: Session) -> dict:
    """
    Replay the chain. Recompute each entry's expected hash and compare.

    Returns a dict shaped like:
        {"valid": True, "count": N}
    or, on a tamper:
        {"valid": False, "broken_at_sequence": N,
         "expected": "abc...", "found": "xyz..."}
    """
    entries = list(
        db.execute(select(AuditEntry).order_by(AuditEntry.sequence.asc()))
        .scalars()
        .all()
    )

    if not entries:
        return {"valid": True, "count": 0}

    prev_hash = GENESIS_HASH

    for entry in entries:
        if entry.prev_hash != prev_hash:
            return {
                "valid": False,
                "broken_at_sequence": entry.sequence,
                "reason": "prev_hash mismatch",
                "expected_prev_hash": prev_hash,
                "found_prev_hash": entry.prev_hash,
            }

        canonical = {
            "agent_name": entry.agent_name,
            "agent_version": entry.agent_version,
            "model_name": entry.model_name,
            "input_hash": entry.input_hash,
            "output": entry.output,
            "confidence": round(float(entry.confidence or 0.0), 3),
            "citations": entry.citations or [],
            "reasoning": entry.reasoning or "",
            "verifier_votes": entry.verifier_votes or [],
            "prev_hash": entry.prev_hash,
            "timestamp": entry.timestamp.isoformat() + "Z",
        }
        recomputed = _sha256(_canonical_json(canonical))

        if recomputed != entry.entry_hash:
            return {
                "valid": False,
                "broken_at_sequence": entry.sequence,
                "reason": "entry_hash mismatch (row contents modified)",
                "expected_entry_hash": recomputed,
                "found_entry_hash": entry.entry_hash,
            }

        prev_hash = entry.entry_hash

    return {"valid": True, "count": len(entries)}
