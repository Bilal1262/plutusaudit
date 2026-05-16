"""
VeridianAI FastAPI application.

Routes:
    POST   /process-invoice          - upload PDF, kick off pipeline, return job_id
    GET    /stream/{job_id}          - SSE stream of agent progress
    GET    /demo-invoices             - demo invoice catalog (clean + fraud metadata)
    GET    /demo-invoices/{filename} - serve whitelisted demo PDF from data/clean|fraud
    GET    /invoices                 - paginated invoice history
    GET    /invoices/{invoice_id}    - full result for one invoice
    GET    /audit-log                - paginated audit entries
    GET    /audit-log/verify         - run verify_chain()
    POST   /audit-log/{id}/override  - record human override
    GET    /vendors                  - list vendors
    POST   /vendors/approve          - add or approve a vendor
    DELETE /vendors/{vendor_id}      - remove a vendor master row
    GET    /analytics                - CFO dashboard aggregates
    GET    /health                   - simple health check
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from collections import defaultdict

from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend import config
from backend.agents.accountant import classify_invoice
from backend.agents.doc_intel import check_extraction_viability, extract_invoice
from backend.agents.explainer import run_explainer
from backend.agents.fraud import detect_fraud
from backend.agents.verifier import verify_and_retry
from backend.audit.chain import verify_chain
from backend.audit.models import AuditEntry
from backend.db import create_all_tables
from backend.db.models import Invoice, JournalEntry, Vendor
from backend.db.session import SessionLocal, engine, get_db

logger = logging.getLogger("veridianai")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# ── Demo invoice catalog (filenames must exist under data/clean or data/fraud) ─
_DEMO_CLEAN = [
    {
        "filename": "clean_01_software_subscription.pdf",
        "label": "Software Subscription",
        "vendor": "Salesforce Ltd",
        "amount": "$24,000",
        "expected_outcome": "IFRS 15 · Prepaid Expenses",
        "description": "Multi-period SaaS — deferral vs expense classification.",
    },
    {
        "filename": "clean_03_legal_services.pdf",
        "label": "Legal Services",
        "vendor": "Morrison & Foerster LLP",
        "amount": "$18,500",
        "expected_outcome": "ASC 720 · Professional Fees",
        "description": "Outside counsel — expense as incurred.",
    },
    {
        "filename": "clean_04_it_equipment.pdf",
        "label": "IT Equipment",
        "vendor": "Dell Technologies",
        "amount": "$12,400",
        "expected_outcome": "IAS 16 · Fixed Assets",
        "description": "Capitalizable laptops/monitors vs expense threshold.",
    },
    {
        "filename": "clean_08_facilities_management.pdf",
        "label": "Facilities Management",
        "vendor": "BrightCare Facilities Ltd",
        "amount": "$3,200",
        "expected_outcome": "ASC 720 · Facilities OPEX",
        "description": "Janitorial / grounds — operating expense.",
    },
    {
        "filename": "clean_02_office_supplies.pdf",
        "label": "Office Supplies",
        "vendor": "Staples Business",
        "amount": "$847",
        "expected_outcome": "ASC 720 · Office Supplies",
        "description": "Consumables — expense classification.",
    },
]

_DEMO_FRAUD = [
    {
        "filename": "fraud_02_duplicate.pdf",
        "label": "Duplicate Invoice",
        "vendor": "Global Telecom SA",
        "amount": "$11,250",
        "expected_outcome": "BLOCKED · exact_duplicate",
        "description": "Same vendor/amount as a posted invoice.",
    },
    {
        "filename": "fraud_01_round_number.pdf",
        "label": "Round Number",
        "vendor": "Apex Consulting LLC",
        "amount": "$10,000",
        "expected_outcome": "REVIEW · round_number + missing_po",
        "description": "Round amount with weak procurement trail.",
    },
    {
        "filename": "fraud_03_shell_company.pdf",
        "label": "Shell Company",
        "vendor": "Vendor Services LLC",
        "amount": "$15,000",
        "expected_outcome": "REVIEW · vague_description + new_vendor",
        "description": "Thin vendor profile and vague scope wording.",
    },
    {
        "filename": "fraud_04_invoice_splitting.pdf",
        "label": "Invoice Splitting",
        "vendor": "Office Supplies Co",
        "amount": "$4,990",
        "expected_outcome": "REVIEW · below_threshold",
        "description": "Just under approval band — splitting pattern risk.",
    },
    {
        "filename": "fraud_10_bank_account_change.pdf",
        "label": "Bank Account Change",
        "vendor": "Trusted Vendor Inc",
        "amount": "$22,000",
        "expected_outcome": "BLOCKED · bank_account_change",
        "description": "Payment instructions altered near disbursement.",
    },
]

ALLOWED_DEMO_FILENAMES: frozenset[str] = frozenset(
    r["filename"] for r in (*_DEMO_CLEAN, *_DEMO_FRAUD)
)


def _safe_demo_basename(filename: str) -> str:
    """Reject path traversal; only bare .pdf filenames on the whitelist."""
    if not filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404, detail="not found")
    base = Path(filename).name
    if filename != base:
        raise HTTPException(status_code=404, detail="not found")
    if not base.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="not found")
    if base not in ALLOWED_DEMO_FILENAMES:
        raise HTTPException(status_code=404, detail="not found")
    return base


# ── App + CORS ────────────────────────────────────────────────────────────────
app = FastAPI(title="VeridianAI", version=config.AGENT_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo-mode CORS
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── In-memory job registry ────────────────────────────────────────────────────
# Each job has:
#   queue   : asyncio.Queue of SSE event dicts (None = sentinel: stream done)
#   status  : "running" | "complete" | "error"
#   result  : final pipeline dict (after explainer)
#   created : float ts
JOBS: dict[str, dict] = {}


# ── Retriever singleton on startup ────────────────────────────────────────────
@app.on_event("startup")
def _startup() -> None:
    # Make sure tables exist
    try:
        create_all_tables()
    except Exception as exc:  # noqa: BLE001
        logger.error("create_all_tables failed: %s", exc)

    # Seed vendors if empty
    try:
        with SessionLocal() as db:
            if db.query(Vendor).count() == 0:
                from scripts.seed_db import seed_vendors

                seed_vendors()
                logger.info("Seeded default vendors")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vendor seeding skipped: %s", exc)

    # Pre-load the RAG index
    try:
        from backend.rag.retriever import get_retriever

        get_retriever()
        logger.info("RAG index loaded")
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG index not loaded at startup: %s", exc)


# ── Pipeline orchestration ────────────────────────────────────────────────────
async def _emit(job_id: str, payload: dict) -> None:
    """Push a payload onto the SSE queue."""
    queue: asyncio.Queue = JOBS[job_id]["queue"]
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    await queue.put(payload)


async def _run_pipeline(job_id: str, file_bytes: bytes, filename: str, invoice_id: str) -> None:
    """Run the 5-agent pipeline in the background."""
    t0 = time.time()
    job = JOBS[job_id]
    job["status"] = "running"

    db: Session = SessionLocal()
    invoice_row: Optional[Invoice] = None
    pipeline: dict = {"job_id": job_id, "filename": filename, "size": len(file_bytes)}

    try:
        invoice_row = db.query(Invoice).filter_by(id=invoice_id).first()
        if invoice_row is None:
            # Defensive fallback: should not happen because /process-invoice creates this row.
            invoice_row = Invoice(
                id=invoice_id,
                filename=filename,
                status="processing",
                currency="USD",
            )
            db.add(invoice_row)
            db.commit()
            db.refresh(invoice_row)
        pipeline["invoice_id"] = invoice_row.id

        # ── Agent 1: Doc Intel ─────────────────────────────────────────────
        await _emit(job_id, {"agent": "doc_intel", "status": "running"})
        extraction = await asyncio.to_thread(
            extract_invoice, file_bytes, filename
        )
        viable, failures = check_extraction_viability(extraction)
        extraction.setdefault("extraction_warnings", [])
        if not viable:
            extraction["requires_human_review"] = True
            extraction["extraction_warnings"].append(
                "Critical fields missing — manual review required before processing"
            )
            extraction["extraction_warnings"].extend(failures)
            extraction["extraction_confidence"] = min(
                float(extraction.get("extraction_confidence", 1.0) or 1.0), 0.4
            )
        pipeline["extraction"] = extraction
        await _emit(
            job_id,
            {
                "agent": "doc_intel",
                "status": "complete",
                "confidence": extraction.get("extraction_confidence", 0.0),
                "data": extraction,
            },
        )

        # Update existing Invoice row (created at upload time)
        invoice_row.vendor_name = extraction.get("vendor_name")
        invoice_row.invoice_number = extraction.get("invoice_number")
        invoice_row.grand_total = float(extraction.get("grand_total") or 0.0) or None
        invoice_row.currency = (extraction.get("currency") or "USD")[:3]
        invoice_row.status = "processing"
        db.commit()
        db.refresh(invoice_row)

        # ── Agent 2 + 3: Accountant & Fraud (parallel; both consume extraction only)
        await _emit(job_id, {"agent": "accountant", "status": "running"})
        await _emit(job_id, {"agent": "fraud", "status": "running"})

        def _detect_fraud_isolated():
            sess = SessionLocal()
            try:
                return detect_fraud(
                    extraction, db=sess, invoice_id=invoice_row.id
                )
            finally:
                sess.close()

        accountant, fraud = await asyncio.gather(
            asyncio.to_thread(classify_invoice, extraction),
            asyncio.to_thread(_detect_fraud_isolated),
        )
        pipeline["accountant"] = accountant
        pipeline["fraud"] = fraud
        pipeline["accountant"]["fraud_score"] = fraud.get("risk_score")
        await _emit(
            job_id,
            {
                "agent": "accountant",
                "status": "complete",
                "confidence": float(accountant.get("confidence", 0.0) or 0.0),
                "data": {k: v for k, v in accountant.items() if k != "retrieved_chunks"},
            },
        )
        fraud_conf = 1.0 - (fraud.get("risk_score", 0) / 100.0)
        await _emit(
            job_id,
            {
                "agent": "fraud",
                "status": "complete",
                "confidence": round(fraud_conf, 3),
                "data": fraud,
            },
        )

        # ── Agent 4: Verifier (async; emits its own retry events) ──────────
        await _emit(job_id, {"agent": "verifier", "status": "running"})

        async def verifier_event_hook(payload: dict) -> None:
            await _emit(job_id, payload)

        verifier = await verify_and_retry(
            extraction,
            accountant,
            on_event=verifier_event_hook,
        )
        # Verifier may have replaced the accountant via retry - sync it
        pipeline["accountant"] = verifier.get("accountant_output", accountant)
        pipeline["verifier"] = verifier
        pipeline["verdict"] = verifier.get("verdict")
        pipeline["final_confidence"] = verifier.get("final_confidence", 0.0)

        await _emit(
            job_id,
            {
                "agent": "verifier",
                "status": "complete" if verifier.get("verdict") != "ESCALATED" else "failed",
                "confidence": float(verifier.get("final_confidence", 0.0) or 0.0),
                "attempt": verifier.get("attempt", 1),
                "data": {
                    "verdict": verifier.get("verdict"),
                    "votes": verifier.get("verifier_votes"),
                    "passed_count": verifier.get("passed_count"),
                    "accountant_output": verifier.get("accountant_output"),
                },
            },
        )

        # If fraud said block, override verdict
        if fraud.get("tier") == "block":
            pipeline["verdict"] = "BLOCKED"
        # Hard business rule: vague description + high fraud score -> human review.
        if (
            (fraud.get("signals") or {}).get("vague_description")
            and float(fraud.get("risk_score") or 0) > 50
        ):
            pipeline["accountant"]["requires_human_review"] = True
            pipeline["accountant"].setdefault("guard_warnings", []).append(
                "vague_description_with_high_fraud_score_forced_review"
            )

        # ── Agent 5: Explainer ─────────────────────────────────────────────
        await _emit(job_id, {"agent": "explainer", "status": "running"})
        pipeline = await asyncio.to_thread(
            run_explainer, pipeline, db, invoice_row.id
        )
        await _emit(
            job_id,
            {
                "agent": "explainer",
                "status": "complete",
                "confidence": pipeline.get("final_confidence", 0.0),
                "data": pipeline.get("explanation"),
            },
        )

        # Finalize Invoice row
        invoice_row.status = (
            "blocked"
            if pipeline.get("verdict") == "BLOCKED"
            else "flagged"
            if pipeline.get("verdict") in ("ESCALATED", "APPROVED_WITH_WARNING")
            else "complete"
        )
        invoice_row.fraud_tier = fraud.get("tier")
        invoice_row.fraud_score = fraud.get("risk_score")
        invoice_row.processing_time_ms = int((time.time() - t0) * 1000)
        invoice_row.pipeline_result = _jsonable(pipeline)

        acc_final = pipeline.get("accountant") or {}
        debit_acct = (acc_final.get("gl_account_debit") or "").strip()
        if debit_acct:
            amt_je = acc_final.get("amount")
            try:
                amt_val = float(
                    amt_je if amt_je is not None else invoice_row.grand_total or 0
                )
            except (TypeError, ValueError):
                amt_val = float(invoice_row.grand_total or 0)
            db.add(
                JournalEntry(
                    invoice_id=invoice_row.id,
                    gl_account_debit=debit_acct,
                    gl_account_credit=str(acc_final.get("gl_account_credit") or ""),
                    amount=amt_val,
                    standard_cited=acc_final.get("standard_cited"),
                    paragraph_cited=acc_final.get("paragraph_cited"),
                    confidence=float(acc_final.get("confidence") or 0.0),
                    requires_human_review=bool(acc_final.get("requires_human_review")),
                    deferral_required=bool(acc_final.get("deferral_required")),
                    amortization_schedule=acc_final.get("amortization_schedule"),
                    reasoning=acc_final.get("reasoning"),
                )
            )

        db.commit()

        await _emit(
            job_id,
            {
                "agent": "complete",
                "status": "complete",
                "data": {
                    "invoice_id": invoice_row.id,
                    "verdict": pipeline.get("verdict"),
                    "audit_entries": pipeline.get("audit_entries", []),
                },
            },
        )

        job["result"] = pipeline
        job["status"] = "complete"

    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline failed: %s", exc)
        await _emit(
            job_id,
            {"agent": "error", "status": "failed", "data": {"error": str(exc)}},
        )
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        # Sentinel - close the stream
        await JOBS[job_id]["queue"].put(None)
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


def _jsonable(obj):
    """Strip non-JSON-serialisable bits (numpy scalars, datetime) for storage."""
    return json.loads(json.dumps(obj, default=str))


# ── routes ────────────────────────────────────────────────────────────────────
def _aggregate_gl_breakdown(db: Session, *, limit: int = 6) -> list[dict]:
    rows = (
        db.query(JournalEntry.gl_account_debit, func.sum(JournalEntry.amount))
        .group_by(JournalEntry.gl_account_debit)
        .order_by(func.sum(JournalEntry.amount).desc())
        .limit(limit)
        .all()
    )
    if rows:
        return [
            {"account": row[0], "amount": float(row[1] or 0)} for row in rows if row[0]
        ]

    totals: dict[str, float] = defaultdict(float)
    inv_rows = db.query(Invoice).filter(Invoice.pipeline_result.isnot(None)).all()
    for inv in inv_rows:
        acc = (inv.pipeline_result or {}).get("accountant") or {}
        debit = acc.get("gl_account_debit")
        if not debit:
            continue
        amt_raw = acc.get("amount")
        try:
            val = float(
                amt_raw if amt_raw is not None else inv.grand_total or 0,
            )
        except (TypeError, ValueError):
            val = float(inv.grand_total or 0)
        totals[str(debit)] += val

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"account": k, "amount": v} for k, v in ranked]


@app.get("/analytics")
def get_analytics(db: Session = Depends(get_db)) -> dict:
    """
    Aggregate metrics for the CFO Analytics dashboard.
    Reads from invoices and journal_entries (with pipeline JSON fallback for GL).
    """
    total = db.query(func.count(Invoice.id)).scalar() or 0

    approved = (
        db.query(func.count(Invoice.id)).filter(Invoice.status == "complete").scalar()
        or 0
    )
    flagged = (
        db.query(func.count(Invoice.id)).filter(Invoice.status == "flagged").scalar()
        or 0
    )
    blocked = (
        db.query(func.count(Invoice.id)).filter(Invoice.status == "blocked").scalar()
        or 0
    )

    touchless = approved
    touchless_rate = round((touchless / total * 100), 1) if total > 0 else 0.0

    avg_ms = (
        db.query(func.avg(Invoice.processing_time_ms))
        .filter(Invoice.processing_time_ms.isnot(None))
        .filter(Invoice.processing_time_ms > 0)
        .scalar()
    )
    avg_seconds = round(float(avg_ms or 0) / 1000.0, 1)

    fraud_sum = (
        db.query(func.sum(Invoice.grand_total))
        .filter(Invoice.status == "blocked")
        .scalar()
    )
    fraud_value = float(fraud_sum or 0)

    manual_cost_per_invoice = 17.00
    ai_cost_per_invoice = 0.04
    cost_saved = round(total * (manual_cost_per_invoice - ai_cost_per_invoice), 2)

    gl_breakdown = _aggregate_gl_breakdown(db, limit=6)

    recent_rows = (
        db.query(Invoice).order_by(Invoice.created_at.desc()).limit(10).all()
    )
    recent_invoices = [
        {
            "filename": inv.filename,
            "vendor": inv.vendor_name,
            "amount": float(inv.grand_total or 0),
            "currency": inv.currency,
            "status": inv.status,
            "fraud_score": inv.fraud_score,
            "created_at": inv.created_at.isoformat() + "Z"
            if inv.created_at
            else None,
        }
        for inv in recent_rows
    ]

    return {
        "summary": {
            "total_processed": total,
            "approved": approved,
            "flagged": flagged,
            "blocked": blocked,
            "touchless_rate": touchless_rate,
            "avg_processing_seconds": avg_seconds,
            "fraud_value_caught": fraud_value,
            "cost_saved": cost_saved,
        },
        "gl_breakdown": gl_breakdown,
        "recent_invoices": recent_invoices,
    }


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    rag_loaded = False
    try:
        from backend.rag.retriever import _global_retriever

        rag_loaded = _global_retriever is not None and _global_retriever.is_loaded()
    except Exception:  # noqa: BLE001
        pass
    db_ok = False
    try:
        db.execute(select(1))
        db_ok = True
    except Exception:  # noqa: BLE001
        pass
    return {
        "status": "ok",
        "rag_loaded": rag_loaded,
        "db_connected": db_ok,
        "env": config.ENVIRONMENT,
        "version": config.AGENT_VERSION,
    }


@app.get("/demo-invoices")
def list_demo_invoices() -> dict:
    """Judge-facing catalog of bundled demo PDFs (paths under data/clean and data/fraud)."""
    return {"clean": _DEMO_CLEAN, "fraud": _DEMO_FRAUD}


@app.get("/demo-invoices/{filename}")
def serve_demo_invoice(filename: str) -> FileResponse:
    """Serve a whitelisted demo PDF; clean/ tried before fraud/."""
    safe = _safe_demo_basename(filename)
    clean_path = config.DATA_DIR / "clean" / safe
    fraud_path = config.DATA_DIR / "fraud" / safe
    if clean_path.is_file():
        return FileResponse(
            path=str(clean_path),
            media_type="application/pdf",
            filename=safe,
        )
    if fraud_path.is_file():
        return FileResponse(
            path=str(fraud_path),
            media_type="application/pdf",
            filename=safe,
        )
    raise HTTPException(status_code=404, detail="demo PDF not found on disk")


@app.post("/process-invoice")
async def process_invoice(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(400, "filename required")
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")

    # Create the invoice record once at upload time, then update it through the pipeline.
    db = SessionLocal()
    invoice_id = str(uuid.uuid4())
    try:
        seed_row = Invoice(
            id=invoice_id,
            filename=file.filename,
            status="processing",
            currency="USD",
        )
        db.add(seed_row)
        db.commit()
    finally:
        db.close()

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "queue": asyncio.Queue(),
        "status": "queued",
        "created": time.time(),
        "filename": file.filename,
        "invoice_id": invoice_id,
    }
    asyncio.create_task(_run_pipeline(job_id, content, file.filename, invoice_id))
    return {"job_id": job_id, "status": "queued", "invoice_id": invoice_id}


@app.get("/stream/{job_id}")
async def stream(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")

    queue: asyncio.Queue = JOBS[job_id]["queue"]

    async def event_gen():
        while True:
            payload = await queue.get()
            if payload is None:
                yield "event: end\ndata: {}\n\n"
                break
            yield f"data: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # important for nginx proxying
        },
    )


@app.get("/invoices")
def list_invoices(
    page: int = 1, page_size: int = 50, db: Session = Depends(get_db)
) -> dict:
    offset = max(0, (page - 1) * page_size)
    rows = (
        db.query(Invoice)
        .order_by(Invoice.upload_timestamp.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": r.id,
            "filename": r.filename,
            "upload_timestamp": r.upload_timestamp.isoformat() + "Z"
            if r.upload_timestamp
            else None,
            "vendor_name": r.vendor_name,
            "invoice_number": r.invoice_number,
            "grand_total": float(r.grand_total) if r.grand_total is not None else None,
            "currency": r.currency,
            "status": r.status,
            "fraud_tier": r.fraud_tier,
            "fraud_score": r.fraud_score,
            "processing_time_ms": r.processing_time_ms,
        }
        for r in rows
    ]
    return {"items": items, "page": page, "page_size": page_size}


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(Invoice).filter_by(id=invoice_id).first()
    if not row:
        raise HTTPException(404, "invoice not found")
    return {
        "id": row.id,
        "filename": row.filename,
        "upload_timestamp": row.upload_timestamp.isoformat() + "Z"
        if row.upload_timestamp
        else None,
        "vendor_name": row.vendor_name,
        "invoice_number": row.invoice_number,
        "grand_total": float(row.grand_total) if row.grand_total is not None else None,
        "currency": row.currency,
        "status": row.status,
        "fraud_tier": row.fraud_tier,
        "fraud_score": row.fraud_score,
        "processing_time_ms": row.processing_time_ms,
        "pipeline_result": row.pipeline_result,
    }


@app.get("/audit-log")
def audit_log(
    page: int = 1, page_size: int = 50, db: Session = Depends(get_db)
) -> dict:
    offset = max(0, (page - 1) * page_size)
    rows = (
        db.query(AuditEntry)
        .order_by(AuditEntry.sequence.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return {
        "items": [r.to_dict() for r in rows],
        "page": page,
        "page_size": page_size,
        "total": db.query(AuditEntry).count(),
    }


@app.get("/audit-log/verify")
def audit_log_verify(db: Session = Depends(get_db)) -> dict:
    return verify_chain(db)


class OverrideRequest(BaseModel):
    reason: str
    new_classification: Optional[str] = None
    user_id: Optional[str] = "human-operator"


class VendorApproveRequest(BaseModel):
    vendor_name: str
    approved_by: str = "user"


def _canonical_vendor_storage(raw: str) -> str:
    """
    Canonical key aligned with fraud._check_new_vendor invoice normalization:
    upper-case and spaces → underscores so approved vendors match extraction.
    """
    return (raw or "").strip().upper().replace(" ", "_")


@app.post("/vendors/approve")
def approve_vendor(
    req: VendorApproveRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Create or update an approved vendor master row."""
    raw = req.vendor_name.strip()
    if not raw:
        raise HTTPException(400, "vendor_name required")
    canon = _canonical_vendor_storage(raw)

    existing = db.query(Vendor).filter(Vendor.name == canon).first()
    if not existing and len(raw) >= 4:
        existing = (
            db.query(Vendor)
            .filter(Vendor.name.ilike(f"%{raw}%"))
            .first()
        )

    if existing:
        existing.is_approved = True
        db.commit()
        db.refresh(existing)
        return {"status": "updated", "vendor": existing.name}

    vendor = Vendor(
        name=canon,
        is_approved=True,
        invoice_count=0,
    )
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return {"status": "created", "vendor": vendor.name}


@app.delete("/vendors/{vendor_id}")
def delete_vendor(vendor_id: str, db: Session = Depends(get_db)) -> dict:
    """Remove a vendor from the vendor master."""
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(404, "vendor not found")
    db.delete(vendor)
    db.commit()
    return {"status": "removed", "vendor_id": vendor_id}


@app.post("/audit-log/{entry_id}/override")
def override_entry(
    entry_id: str, body: OverrideRequest, db: Session = Depends(get_db)
) -> dict:
    """
    Records a human override as a NEW append-only audit entry whose output
    references the original entry_id. The original entry is never mutated.
    """
    from backend.audit.chain import append_entry

    original = db.query(AuditEntry).filter_by(entry_id=entry_id).first()
    if not original:
        raise HTTPException(404, "entry not found")

    payload = {
        "override_of": entry_id,
        "reason": body.reason,
        "new_classification": body.new_classification,
        "original_agent": original.agent_name,
    }
    new_entry = append_entry(
        db,
        agent_name="human_override",
        model_name="human",
        input_data={"target_entry": entry_id},
        output_data=payload,
        confidence=1.0,
        citations=[entry_id],
        reasoning=body.reason,
        user_id=body.user_id or "human-operator",
        invoice_id=original.invoice_id,
    )
    # Mark override on the existing row for fast lookup (this DOES modify
    # the row, intentionally - but we also append a new immutable entry,
    # so the audit chain still detects it as a tamper unless we treat
    # human_override as a separately-tracked annotation. For demo purposes
    # we ALSO write a new entry).
    return {
        "ok": True,
        "new_entry_id": new_entry.entry_id,
        "new_sequence": new_entry.sequence,
        "new_hash": new_entry.entry_hash,
    }


@app.get("/vendors")
def list_vendors(db: Session = Depends(get_db)) -> list:
    return [
        {
            "id": v.id,
            "name": v.name,
            "is_approved": v.is_approved,
            "invoice_count": v.invoice_count,
            "created_at": v.created_at.isoformat() + "Z" if v.created_at else None,
        }
        for v in db.query(Vendor)
        .order_by(desc(Vendor.is_approved), Vendor.name.asc())
        .all()
    ]


# ── tamper demo helper (development only) ─────────────────────────────────────
@app.post("/_demo/tamper/{entry_id}")
def demo_tamper(entry_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Demo-only endpoint: directly mutates an audit row so the next call to
    /audit-log/verify will return a tamper-detected response. NEVER enable
    in production.
    """
    if config.ENVIRONMENT == "production":
        raise HTTPException(403, "disabled in production")
    row = db.query(AuditEntry).filter_by(entry_id=entry_id).first()
    if not row:
        raise HTTPException(404, "entry not found")
    row.output = dict(row.output or {})
    row.output["_tampered"] = True
    db.commit()
    return {"ok": True, "tampered_entry_id": entry_id, "tampered_sequence": row.sequence}
