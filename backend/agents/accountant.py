
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from backend import config
from backend.agents.doc_intel import _get_gemini_model, _safe_json_loads
from backend.rag.retriever import HybridRetriever, get_retriever

logger = logging.getLogger(__name__)

_PROMPT_PATH = config.PROMPTS_DIR / "accountant.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ── retrieval query construction ──────────────────────────────────────────────

_FRAUD_QUERY_SUBSTRINGS = (
    "duplicate",
    "fraud",
    "blocked",
    "signal",
)


def _build_query(invoice: dict) -> str:
    """
    Build retrieval text for the accountant agent only — vendor, line wording,
    and payment terms. No amounts/currency (fraud-heavy signals), no fields
    that could bake in fraud wording from upstream pipelines.
    """
    parts: list[str] = []
    vendor = invoice.get("vendor_name") or ""
    if vendor:
        parts.append(f"Vendor: {vendor}")

    items = invoice.get("line_items") or []
    if items:
        descs: list[str] = []
        for li in items[:3]:
            d = str(li.get("description") or "")
            dl = d.lower()
            if any(bad in dl for bad in _FRAUD_QUERY_SUBSTRINGS):
                continue
            descs.append(d)
        if descs:
            parts.append("Line items: " + "; ".join(descs))

    payment = invoice.get("payment_terms")
    if payment:
        parts.append(f"Terms: {payment}")

    return " | ".join(parts) or "professional services expense classification"


# ── faithfulness guard ────────────────────────────────────────────────────────

def _citation_in_chunks(
    standard: str, paragraph: str, chunks: list[dict]
) -> bool:
    """
    Return True if (standard, paragraph) matches any retrieved chunk.
    Matching is lenient — standard only needs to appear as a substring
    of the chunk's standard field, handling compound standards like
    'ASC 720 / IAS 1' and slash-separated multi-standard entries.
    """
    if not standard:
        return False

    # Normalise cited values
    std_norm = standard.strip().lower().replace(" ", "")
    par_norm = (
        paragraph.strip().lower()
        .replace(" ", "")
        .replace("para", "")
        .replace(".", "")
        .strip("-")
    ) if paragraph else ""

    for chunk in chunks:
        # Normalise chunk standard — handle compound entries
        cs_raw = (chunk.get("standard") or "")
        # Split on slash, comma, ampersand to handle "ASC 720 / IAS 1"
        cs_parts = re.split(r"[/,&]", cs_raw)
        cs_norms = [
            p.strip().lower().replace(" ", "")
            for p in cs_parts
        ]

        # Normalise chunk paragraph
        cp = (chunk.get("paragraph") or "")
        cp_norm = (
            cp.strip().lower()
            .replace(" ", "")
            .replace("para", "")
            .replace(".", "")
            .strip("-")
        )

        # Standard match: cited standard must appear in at least one part
        std_match = any(
            std_norm in cs or cs in std_norm
            for cs in cs_norms
            if cs
        )

        # Paragraph match: exact after normalisation, or cited is substring
        par_match = (
            not par_norm          # no paragraph cited — accept
            or par_norm == cp_norm
            or par_norm in cp_norm
            or cp_norm in par_norm
        )

        if std_match and par_match:
            return True

    return False

# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_amount(invoice: dict) -> float:
    try:
        return round(float(invoice.get("grand_total") or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _invoice_text(invoice: dict) -> str:
    items = invoice.get("line_items") or []
    return " ".join(str(li.get("description") or "") for li in items).lower()


def _normalise_gl_account(name: str) -> str:
    """Map model-generated GL account names to canonical chart-of-accounts labels."""
    n = (name or "").strip().lower()
    if "professional" in n and "service" in n:
        return "Professional Services Expense"
    if "legal" in n and ("expense" in n or "fee" in n):
        return "Professional Services Expense"
    if "office" in n and "suppl" in n:
        return "Office Supplies Expense"
    if "prepaid" in n and "maintenance" in n:
        return "Prepaid Maintenance"
    if "prepaid" in n:
        return "Prepaid Expenses"
    if "subscription" in n and "expense" in n:
        return "Subscription Expense"
    if "computer" in n or ("equipment" in n and "it" in n):
        return "Computer Equipment"
    if "it" in n and "expense" in n:
        return "IT Equipment Expense"
    if "furniture" in n or "fitting" in n:
        return "Furniture and Fittings"
    if "suspense" in n:
        return "Suspense Account"
    if "unclassified" in n and "manual" in n:
        return "Unclassified Expense - Manual Review"
    if "unclassified" in n:
        return "Unclassified Expense - Review"
    if "accounts payable" in n or n == "ap":
        return "Accounts Payable"
    if "marketing" in n or "advertising" in n:
        return "Marketing Expense"
    if "travel" in n:
        return "Travel Expense"
    if "training" in n or "education" in n:
        return "Training Expense"
    if "rent" in n or "lease" in n:
        return "Rent Expense"
    if "utilities" in n or "electricity" in n or "internet" in n:
        return "Utilities Expense"
    if "maintenance" in n or "repair" in n:
        return "Maintenance Expense"
    if "recruitment" in n or "staffing" in n:
        return "Recruitment Expense"
    if "insurance" in n:
        return "Insurance Expense"
    if "research" in n and "development" in n:
        return "R&D Expense"
    if "intangible" in n and "software" in n:
        return "Intangible Assets - Software"
    # Return as-is if no match — better than silently mangling an unknown account
    return name


def _amount_from_value(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ── minimal hard guards ───────────────────────────────────────────────────────

def _apply_hard_classification_rules(parsed: dict, invoice: dict) -> None:
    """
    Minimal guards only. Classification is driven by RAG + Gemini.
    Hard keyword overrides have been removed — the expanded corpus
    (gaap_ifrs_rules_expanded_rag_audit_ai.txt) handles all standard
    invoice types generically through retrieval.

    Guards retained:
        1. Zero / missing amount  → Unclassified + human review
        2. Unknown vendor         → human review flag
        3. Software subscription  → force IFRS 15 + amortisation schedule
           (structural output transform, not a classification override)
        4. GL account normalisation to chart-of-accounts labels
    """
    amount = _safe_amount(invoice)
    vendor = str(invoice.get("vendor_name") or "").strip().lower()
    txt = _invoice_text(invoice)

    # ── Guard 1: zero / missing amount ────────────────────────────────────────
    if amount <= 0:
        parsed["confidence"] = 0.1
        parsed["requires_human_review"] = True
        parsed["gl_account_debit"] = "Unclassified Expense - Manual Review"
        parsed["gl_account_credit"] = "Accounts Payable"
        parsed["standard_cited"] = "Insufficient Data"
        parsed["paragraph_cited"] = "N/A"
        parsed["deferral_required"] = False
        parsed["amortization_schedule"] = None
        parsed.setdefault("guard_warnings", []).append(
            "grand_total_missing_or_zero_forced_review"
        )
        parsed["reasoning"] = (
            f"{parsed.get('reasoning', '').strip()} "
            "Grand total is zero or missing — classification deferred to manual review."
        ).strip()
        return  # no further processing makes sense

    # ── Guard 2: unknown / missing vendor ─────────────────────────────────────
    if vendor in {"", "unknown", "n/a", "none"}:
        parsed["requires_human_review"] = True
        parsed["confidence"] = min(
            float(parsed.get("confidence", 0.4) or 0.4), 0.4
        )
        parsed.setdefault("guard_warnings", []).append(
            "vendor_name_missing_forced_review"
        )

    # ── Guard 3: software subscription deferral ───────────────────────────────
    # Retained because it requires generating a month-by-month amortisation
    # schedule — a structural output the prompt alone does not guarantee.
    # The check is intentionally narrow (requires explicit subscription/SaaS
    # keywords) so it does not misfire on legal or consulting invoices.
    is_software = any(
        k in txt
        for k in (
            "subscription",
            "saas",
            "software license",
            "annual license",
            "cloud platform",
            "annual subscription",
        )
    )
    if is_software:
        parsed["standard_cited"] = "IFRS 15"
        parsed["paragraph_cited"] = "Para 31"
        parsed["deferral_required"] = True
        parsed["gl_account_debit"] = "Prepaid Expenses"
        parsed["gl_account_credit"] = "Accounts Payable"
        if not parsed.get("amortization_schedule") and amount > 0:
            parsed["amortization_schedule"] = {
                "monthly_amount": round(amount / 12, 2),
                "months": 12,
                "monthly_debit": "Subscription Expense",
                "monthly_credit": "Prepaid Expenses",
            }

    # ── Guard 4: normalise GL account labels ──────────────────────────────────
    parsed["gl_account_debit"] = _normalise_gl_account(
        parsed.get("gl_account_debit", "")
    )
    parsed["gl_account_credit"] = _normalise_gl_account(
        parsed.get("gl_account_credit", "")
    )


# ── deterministic fallback (Gemini unavailable) ───────────────────────────────

def _deterministic_fallback_classification(
    invoice: dict, chunks: list[dict], error: str
) -> dict:
    """
    Fallback when Gemini is unavailable (quota / network error).
    Uses simple keyword heuristics + top retrieved chunk metadata.
    Hard furniture / equipment branches removed — those are RAG-driven.
    """
    amount = _safe_amount(invoice)
    text = " ".join(
        str(li.get("description") or "")
        for li in (invoice.get("line_items") or [])
    ).lower()
    terms = str(invoice.get("payment_terms") or "").lower()
    vendor = str(invoice.get("vendor_name") or "").lower()
    merged = f"{text} {terms} {vendor}".strip()

    # ── keyword → account / standard mapping ─────────────────────────────────
    if any(
        k in merged
        for k in (
            "subscription", "annual", "prepaid", "license",
            "saas", "software", "cloud platform", "annual subscription",
        )
    ):
        debit = "Prepaid Expenses"
        credit = "Accounts Payable"
        deferral_required = True
        standard = "IFRS 15"
        paragraph_cited = "Para 31"

    elif any(
        k in merged
        for k in (
            "legal", "law", "attorney", "solicitor", "counsel",
            "audit fee", "fulbright", "chambers", "llp",
            "professional service", "advisory service",
        )
    ):
        debit = "Professional Services Expense"
        credit = "Accounts Payable"
        deferral_required = False
        standard = "ASC 720"
        paragraph_cited = "Para 25-1"

    elif any(
        k in merged
        for k in (
            "consult", "strategy", "management consult",
            "advisory", "professional fees",
        )
    ):
        debit = "Professional Services Expense"
        credit = "Accounts Payable"
        deferral_required = False
        standard = "ASC 720"
        paragraph_cited = "Para 25-1"

    else:
        # Generic fallback — use top retrieved chunk if available
        top = chunks[0] if chunks else {}
        debit = "Unclassified Expense - Review"
        credit = "Accounts Payable"
        deferral_required = False
        standard = top.get("standard") or "ASC 720"
        paragraph = top.get("paragraph")
        paragraph_cited = (
            f"Para {paragraph}"
            if paragraph and not str(paragraph).lower().startswith("para")
            else (paragraph or "Para 25-1")
        )

    result: dict = {
        "reasoning": (
            "Gemini classification unavailable; used deterministic fallback "
            "based on invoice keywords and top retrieved accounting rule. "
            f"Error: {error}"
        ),
        "gl_account_debit": debit,
        "gl_account_credit": credit,
        "amount": amount,
        "standard_cited": standard,
        "paragraph_cited": paragraph_cited,
        "deferral_required": deferral_required,
        "amortization_schedule": (
            {
                "monthly_amount": round(amount / 12, 2) if amount else 0.0,
                "months": 12,
                "monthly_debit": "Subscription Expense",
                "monthly_credit": "Prepaid Expenses",
            }
            if deferral_required and amount
            else None
        ),
        "confidence": 0.55,
        "requires_human_review": True,
        "retrieved_chunk_ids": [c["id"] for c in chunks],
        "retrieved_chunks": chunks,
        "guard_warnings": ["gemini_unavailable_deterministic_fallback"],
        "error": error,
    }

    # Apply minimal guards (zero amount, vendor, normalisation)
    _apply_hard_classification_rules(result, invoice)
    return result


# ── core entry point ──────────────────────────────────────────────────────────

def classify_invoice(
    invoice: dict,
    *,
    retriever: Optional[HybridRetriever] = None,
    use_hyde: bool = True,
    extra_critique: Optional[str] = None,
) -> dict:
    """
    Run RAG + Gemini to produce a GL classification + journal entry.

    `extra_critique` is used by the verifier's retry loop: when verification
    fails, the critique is appended to the prompt as corrective feedback.
    """
    retriever = retriever or get_retriever()

    # ── 1. Retrieve relevant accounting rules ─────────────────────────────────
    query = _build_query(invoice)
    try:
        gemini_for_hyde = _get_gemini_model() if use_hyde else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("accountant: HyDE disabled (no Gemini): %s", exc)
        gemini_for_hyde = None

    chunks = retriever.retrieve(
        query,
        top_k=3,
        use_hyde=use_hyde and gemini_for_hyde is not None,
        gemini_model=gemini_for_hyde,
        exclude_categories=["fraud_control"],
    )
    context_block = retriever.format_context(chunks)
    chunk_ids = [c["id"] for c in chunks]

    # ── 2. Build prompt ───────────────────────────────────────────────────────
    prompt = _load_prompt()
    user_msg = (
        f"=== RETRIEVED CONTEXT (top {len(chunks)} chunks) ===\n"
        f"{context_block}\n\n"
        f"=== INVOICE JSON ===\n{json.dumps(invoice, default=str, indent=2)}\n"
    )
    if extra_critique:
        user_msg += (
            "\n=== VERIFIER CRITIQUE (your previous attempt failed) ===\n"
            f"{extra_critique}\n"
            "Re-do the task correcting EACH issue above. "
            "Explain each correction in `reasoning`.\n"
        )

    # ── 3. Call Gemini ────────────────────────────────────────────────────────
    try:
        model = _get_gemini_model()
        resp = model.generate_content([prompt, user_msg])
        parsed = _safe_json_loads((getattr(resp, "text", None) or "").strip())
    except Exception as exc:  # noqa: BLE001
        logger.error("accountant: Gemini call failed: %s", exc)
        return _deterministic_fallback_classification(invoice, chunks, str(exc))

    # ── 4. Attach retrieval metadata ──────────────────────────────────────────
    parsed.setdefault("retrieved_chunk_ids", chunk_ids)
    parsed["retrieved_chunks"] = chunks

    # ── 5. RAG faithfulness guard ─────────────────────────────────────────────
    # If the model cited a standard/paragraph not in our retrieved corpus,
    # it is hallucinating. Flag for human review and lower confidence.
    grounded = _citation_in_chunks(
        parsed.get("standard_cited", ""),
        parsed.get("paragraph_cited", ""),
        chunks,
    )
    if not grounded:
        parsed["requires_human_review"] = True
        parsed["confidence"] = min(float(parsed.get("confidence", 0.5) or 0.5), 0.5)
        parsed.setdefault("guard_warnings", []).append(
            "citation_not_in_retrieved_context"
        )

    # ── 6. Arithmetic guard ───────────────────────────────────────────────────
    # The journal entry amount must equal the invoice grand_total.
    amt = float(parsed.get("amount") or 0.0)
    gt = _safe_amount(invoice)
    if abs(amt - gt) > 0.01 and gt > 0:
        parsed["amount"] = gt
        parsed.setdefault("guard_warnings", []).append(
            f"amount_corrected_from_{amt:.2f}_to_{gt:.2f}"
        )

    # ── 7. Minimal hard guards + GL normalisation ─────────────────────────────
    _apply_hard_classification_rules(parsed, invoice)

    # ── 8. Confidence threshold guard ─────────────────────────────────────────
    if float(parsed.get("confidence", 0.0)) < config.CONFIDENCE_HUMAN_REVIEW_THRESHOLD:
        parsed["requires_human_review"] = True

    return parsed


# ── smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Test 1: software subscription — expect IFRS 15 Para 31 + deferral
    software_invoice = {
        "vendor_name": "Acme Software Ltd",
        "invoice_number": "INV-001",
        "currency": "USD",
        "subtotal": 2400.00,
        "tax_amount": 0.0,
        "grand_total": 2400.00,
        "payment_terms": "Annual subscription - 12 months",
        "line_items": [
            {
                "description": "Acme Cloud Platform annual subscription",
                "quantity": 1,
                "unit_price": 2400.00,
                "line_total": 2400.00,
            }
        ],
    }

    # Test 2: legal services — expect ASC 720 Para 25-1 Professional Services
    legal_invoice = {
        "vendor_name": "Norton Rose Fulbright",
        "invoice_number": "310233",
        "currency": "GBP",
        "subtotal": 21850.00,
        "tax_amount": 4370.00,
        "grand_total": 26220.00,
        "payment_terms": "30 days",
        "line_items": [
            {
                "description": "Professional and legal advisory services "
                               "including investment proposals and corporate "
                               "structure analysis",
                "quantity": 1,
                "unit_price": 21850.00,
                "line_total": 21850.00,
            }
        ],
    }

    # Test 3: furniture — expect IAS 16 Para 7b Furniture and Fittings
    furniture_invoice = {
        "vendor_name": "Hall-Boyd",
        "invoice_number": "74589240",
        "currency": "USD",
        "subtotal": 11794.44,
        "tax_amount": 1179.44,
        "grand_total": 12973.88,
        "payment_terms": "Net 30",
        "line_items": [
            {
                "description": "YILONG 5.5x8 Handknotted Silk Area Rug",
                "quantity": 1,
                "unit_price": 10560.00,
                "line_total": 10560.00,
            },
            {
                "description": "3D Printed Mat Vortex Illusion Living room Rug",
                "quantity": 3,
                "unit_price": 11.63,
                "line_total": 34.89,
            },
        ],
    }

    tests = [
        ("Software subscription", software_invoice),
        ("Legal services",        legal_invoice),
        ("Furniture / rugs",      furniture_invoice),
    ]

    for label, inv in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {label}")
        print("="*60)
        try:
            out = classify_invoice(inv)
            print(f"  GL Debit:   {out.get('gl_account_debit')}")
            print(f"  GL Credit:  {out.get('gl_account_credit')}")
            print(f"  Standard:   {out.get('standard_cited')} {out.get('paragraph_cited')}")
            print(f"  Confidence: {out.get('confidence')}")
            print(f"  Deferral:   {out.get('deferral_required')}")
            print(f"  Review:     {out.get('requires_human_review')}")
            if out.get("guard_warnings"):
                print(f"  Warnings:   {out['guard_warnings']}")
            if out.get("amortization_schedule"):
                print(f"  Amortise:   {out['amortization_schedule']}")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            raise