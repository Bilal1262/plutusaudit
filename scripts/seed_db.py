"""
Seed the database with clean vendor data.

Run once:
    python -m scripts.seed_db

Optional historical invoice seed:
    python -m scripts.seed_db --with-history
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Allow running both as a module and as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import create_all_tables  # noqa: E402
from backend.db.models import Invoice, Vendor  # noqa: E402
from backend.db.session import session_scope  # noqa: E402


APPROVED_VENDORS = [
    "ACME_SOFTWARE",
    "OFFICE_DEPOT",
    "DELL_COMPUTERS",
    "AWS_CLOUD",
    "MICROSOFT_AZURE",
    "GOOGLE_WORKSPACE",
    "STARBUCKS_CATERING",
    "FEDEX_LOGISTICS",
    "JONES_LAW_LLP",
    "PWC_AUDIT",
]

SUSPICIOUS_VENDORS = ["FASTCONSULT"]


def _hash_account(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def seed_vendors() -> None:
    with session_scope() as db:
        for name in APPROVED_VENDORS:
            if not db.query(Vendor).filter_by(name=name).first():
                db.add(
                    Vendor(
                        name=name,
                        address=f"{name.title().replace('_', ' ')} HQ, USA",
                        bank_account_hash=_hash_account(f"{name}-bank"),
                        is_approved=True,
                        invoice_count=0,
                        created_at=datetime.utcnow() - timedelta(days=400),
                    )
                )
        for name in SUSPICIOUS_VENDORS:
            if not db.query(Vendor).filter_by(name=name).first():
                db.add(
                    Vendor(
                        name=name,
                        address="Unknown address",
                        bank_account_hash=_hash_account(f"{name}-bank"),
                        is_approved=False,
                        invoice_count=0,
                        created_at=datetime.utcnow() - timedelta(days=10),
                    )
                )


def seed_historical_invoices() -> None:
    history_path = Path(__file__).resolve().parent.parent / "data" / "vendor_history.json"
    if not history_path.exists():
        print(f"[seed] vendor_history.json missing at {history_path} - skipping")
        return

    history = json.loads(history_path.read_text())

    with session_scope() as db:
        existing = db.query(Invoice).count()
        if existing >= 20:
            print(f"[seed] Already have {existing} invoices - skipping historical seed")
            return

        seeded = 0
        for vendor_name, invoices in list(history.items())[:3]:
            for entry in invoices[:7]:
                inv = Invoice(
                    filename=f"hist_{entry['invoice_id']}.pdf",
                    vendor_name=vendor_name,
                    invoice_number=entry["invoice_id"],
                    grand_total=entry["amount"],
                    currency="USD",
                    status="complete",
                    fraud_tier="clean",
                    fraud_score=5,
                    upload_timestamp=datetime.fromisoformat(entry["date"]),
                )
                db.add(inv)
                seeded += 1
        print(f"[seed] Seeded {seeded} historical invoices.")


def main() -> None:
    with_history = "--with-history" in sys.argv[1:]
    print("[seed] Ensuring tables exist...")
    create_all_tables()
    print("[seed] Seeding vendors...")
    seed_vendors()
    if with_history:
        print("[seed] Seeding historical invoices...")
        seed_historical_invoices()
    else:
        print("[seed] Skipping historical invoices; invoice table remains clean.")
    print("[seed] Done.")


if __name__ == "__main__":
    main()
