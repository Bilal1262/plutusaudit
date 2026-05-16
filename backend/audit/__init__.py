"""Audit package - hash-chained append-only audit log."""

from .chain import append_entry, verify_chain
from .models import AuditEntry

__all__ = ["AuditEntry", "append_entry", "verify_chain"]
