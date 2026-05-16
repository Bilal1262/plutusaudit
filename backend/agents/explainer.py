"""
Agent 5 - Explainer + Audit Trail.

Two responsibilities:
    1) Produce a plain-English explanation of the pipeline result (Gemini).
    2) Append 5 hash-chained audit entries (one per agent that ran).

Returns the full pipeline result, including the explanation and the list of
audit entry hashes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend import config
from backend.agents.doc_intel import _get_gemini_model, _safe_json_loads
from backend.audit.chain import append_entry

logger = logging.getLogger(__name__)

_PROMPT_PATH = config.PROMPTS_DIR / "explainer.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _resolve_model_name(default_model: str, payload: Optional[dict]) -> str:
    candidate = str((payload or {}).get("model_name") or "").strip()
    if not candidate:
        return default_model
    lowered = candidate.lower()
    if any(tok in lowered for tok in ("fallback", "heuristic", "unknown")):
        return default_model
    return candidate


def _blocked_headline(pipeline: dict) -> str:
    inv = pipeline.get("extraction") or {}
    fraud = pipeline.get("fraud") or {}
    vendor = inv.get("vendor_name") or "Unknown vendor"
    amount = float(inv.get("grand_total") or 0)
    currency = inv.get("currency") or "USD"
    score = int(fraud.get("risk_score") or 0)
    top = (fraud.get("llm_result") or {}).get("top_3_signals") or []
    if top:
        reason = " + ".join(top[:3])
        return (
            f"⚠️ BLOCKED: This {currency} {amount:,.2f} invoice from {vendor} scored "
            f"{score}/100 on fraud detection — {reason}."
        )
    return (
        f"⚠️ BLOCKED: This {currency} {amount:,.2f} invoice from {vendor} scored "
        f"{score}/100 on fraud detection."
    )


def _enforce_blocked_explanation(pipeline: dict, explanation: dict) -> dict:
    fraud = pipeline.get("fraud") or {}
    verdict = pipeline.get("verdict")
    score = int(fraud.get("risk_score") or 0)
    is_blocked = verdict == "BLOCKED" or fraud.get("tier") == "block" or score >= 70
    if not is_blocked:
        return explanation
    explanation = dict(explanation or {})
    explanation["headline"] = _blocked_headline(pipeline)
    rationale = explanation.get("rationale") or ""
    if "blocked" not in rationale.lower():
        explanation["rationale"] = (
            f"Fraud risk scored {score}/100 and crossed the block threshold. "
            f"{rationale}".strip()
        )
    explanation["full_text"] = "\n\n".join(
        [
            explanation.get("headline", ""),
            explanation.get("rationale", ""),
            explanation.get("confidence_statement", ""),
            explanation.get("override_invitation", ""),
        ]
    )
    return explanation


def _fallback_explanation(pipeline: dict) -> dict:
    """Cheap deterministic explanation in case Gemini is unavailable."""
    inv = pipeline.get("extraction") or {}
    acc = pipeline.get("accountant") or {}
    fraud = pipeline.get("fraud") or {}
    verifier = pipeline.get("verifier") or {}

    vendor = inv.get("vendor_name") or "Unknown vendor"
    amount = inv.get("grand_total") or 0
    currency = inv.get("currency") or "USD"
    debit = acc.get("gl_account_debit", "?")
    standard = acc.get("standard_cited", "?")
    paragraph = acc.get("paragraph_cited", "?")
    verdict = pipeline.get("verdict", "UNKNOWN")
    final_conf = pipeline.get("final_confidence", 0.0)

    headline = (
        _blocked_headline(pipeline)
        if verdict == "BLOCKED" or fraud.get("tier") == "block" or int(fraud.get("risk_score", 0) or 0) >= 70
        else (
            f"This {currency} {amount:,.2f} invoice from {vendor} was classified as "
            f"{debit} under {standard} {paragraph} "
            + (
                "and auto-posted."
                if verdict == "APPROVED"
                else (
                    "and approved with a warning."
                    if verdict == "APPROVED_WITH_WARNING"
                    else "and escalated for human review."
                    if verdict == "ESCALATED"
                    else "and blocked for fraud risk."
                )
            )
        )
    )

    fired = (fraud.get("llm_result") or {}).get("top_3_signals", []) or []
    rationale = (
        f"The accountant cited {standard} {paragraph}. "
        f"Fraud check produced score {fraud.get('risk_score', 0)}/100 (tier {fraud.get('tier','clean')}). "
        + (f"Top signals: {', '.join(fired)}. " if fired else "No fraud signals fired. ")
        + f"{verifier.get('passed_count', 0)}/3 verifiers agreed."
    )
    conf_pct = int(round(final_conf * 100))
    confidence_statement = f"Final confidence {conf_pct}%."
    override_invitation = "If you disagree, click Override to record your decision."

    return {
        "headline": headline,
        "rationale": rationale,
        "confidence_statement": confidence_statement,
        "override_invitation": override_invitation,
        "full_text": "\n\n".join(
            [headline, rationale, confidence_statement, override_invitation]
        ),
        "source": "fallback",
    }


def explain(pipeline: dict) -> dict:
    """Generate the plain-English explanation."""
    try:
        model = _get_gemini_model()
        prompt = _load_prompt()
        user_msg = f"PIPELINE:\n{json.dumps(pipeline, default=str, indent=2)}\n"
        resp = model.generate_content([prompt, user_msg])
        parsed = _safe_json_loads((getattr(resp, "text", None) or "").strip())

        # Ensure full_text exists
        if "full_text" not in parsed:
            parsed["full_text"] = "\n\n".join(
                [
                    parsed.get("headline", ""),
                    parsed.get("rationale", ""),
                    parsed.get("confidence_statement", ""),
                    parsed.get("override_invitation", ""),
                ]
            )
        parsed["source"] = "gemini"
        return _enforce_blocked_explanation(pipeline, parsed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("explainer: gemini failed, using deterministic fallback (%s)", exc)
        return _enforce_blocked_explanation(pipeline, _fallback_explanation(pipeline))


# ── audit log helpers ─────────────────────────────────────────────────────────
def write_audit_chain(
    db: Session,
    *,
    invoice_id: str,
    pipeline: dict,
) -> list[dict]:
    """
    Write one audit entry per agent. Returns the list of entry summaries
    (entry_id, sequence, entry_hash) for display in the frontend.
    """
    entries: list[dict] = []

    extraction = pipeline.get("extraction") or {}
    accountant = pipeline.get("accountant") or {}
    fraud = pipeline.get("fraud") or {}
    verifier = pipeline.get("verifier") or {}
    explanation = pipeline.get("explanation") or {}

    # 1) doc_intel
    e1 = append_entry(
        db,
        agent_name="doc_intel",
        model_name=_resolve_model_name(config.GEMINI_MODEL, extraction),
        input_data={"filename": pipeline.get("filename"), "size": pipeline.get("size")},
        output_data=extraction,
        confidence=float(extraction.get("extraction_confidence", 0.0) or 0.0),
        citations=[],
        reasoning=extraction.get("reasoning"),
        invoice_id=invoice_id,
    )
    entries.append({"agent": "doc_intel", "entry_id": e1.entry_id, "sequence": e1.sequence, "entry_hash": e1.entry_hash})

    # 2) accountant
    citations = []
    if accountant.get("standard_cited"):
        citations.append(
            f"{accountant.get('standard_cited')} {accountant.get('paragraph_cited','')}".strip()
        )
    e2 = append_entry(
        db,
        agent_name="accountant",
        model_name=_resolve_model_name(config.GEMINI_MODEL, accountant),
        input_data=extraction,
        output_data={k: v for k, v in accountant.items() if k != "retrieved_chunks"},
        confidence=float(accountant.get("confidence", 0.0) or 0.0),
        citations=citations
        + [
            cid
            for cid in (accountant.get("retrieved_chunk_ids") or [])
            if not str(cid).startswith("fallback_")
        ],
        reasoning=accountant.get("reasoning"),
        invoice_id=invoice_id,
    )
    entries.append({"agent": "accountant", "entry_id": e2.entry_id, "sequence": e2.sequence, "entry_hash": e2.entry_hash})

    # 3) fraud
    fraud_conf = (
        1.0 - (float(fraud.get("risk_score", 0)) / 100.0)
    )
    e3 = append_entry(
        db,
        agent_name="fraud",
        model_name=_resolve_model_name(config.FEATHERLESS_MODEL, fraud.get("llm_result") or {}),
        input_data={"extraction": extraction, "signals": fraud.get("signals")},
        output_data=fraud,
        confidence=round(fraud_conf, 3),
        citations=(fraud.get("llm_result", {}) or {}).get("top_3_signals", []),
        reasoning=(fraud.get("llm_result", {}) or {}).get("reasoning"),
        invoice_id=invoice_id,
    )
    entries.append({"agent": "fraud", "entry_id": e3.entry_id, "sequence": e3.sequence, "entry_hash": e3.entry_hash})

    # 4) verifier
    e4 = append_entry(
        db,
        agent_name="verifier",
        model_name=_resolve_model_name(config.GEMINI_MODEL, verifier),
        input_data={"accountant": {k: v for k, v in accountant.items() if k != "retrieved_chunks"}},
        output_data={k: v for k, v in verifier.items() if k != "accountant_output"},
        confidence=float(verifier.get("final_confidence", 0.0) or 0.0),
        citations=[],
        reasoning=f"verdict={verifier.get('verdict')}, attempts={verifier.get('attempt',1)}",
        verifier_votes=verifier.get("verifier_votes"),
        invoice_id=invoice_id,
    )
    entries.append({"agent": "verifier", "entry_id": e4.entry_id, "sequence": e4.sequence, "entry_hash": e4.entry_hash})

    # 5) explainer
    e5 = append_entry(
        db,
        agent_name="explainer",
        model_name=_resolve_model_name(config.GEMINI_MODEL, explanation),
        input_data={"pipeline_summary": pipeline.get("verdict")},
        output_data=explanation,
        confidence=float(verifier.get("final_confidence", 0.0) or 0.0),
        citations=[],
        reasoning=explanation.get("rationale"),
        invoice_id=invoice_id,
    )
    entries.append({"agent": "explainer", "entry_id": e5.entry_id, "sequence": e5.sequence, "entry_hash": e5.entry_hash})

    return entries


def run_explainer(
    pipeline: dict, db: Optional[Session] = None, invoice_id: Optional[str] = None
) -> dict:
    """
    Produce explanation, optionally write audit entries. Returns the
    augmented pipeline dict (caller stores or returns this).
    """
    pipeline["explanation"] = explain(pipeline)
    pipeline["explained_at"] = datetime.now(timezone.utc).isoformat()

    if db is not None and invoice_id is not None:
        try:
            pipeline["audit_entries"] = write_audit_chain(
                db, invoice_id=invoice_id, pipeline=pipeline
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("explainer: audit chain write failed: %s", exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            pipeline["audit_entries"] = []
            pipeline["audit_error"] = str(exc)
    return pipeline


# ── smoke test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    demo_pipeline = {
        "extraction": {
            "vendor_name": "Acme Software Ltd",
            "grand_total": 2400.00,
            "currency": "USD",
        },
        "accountant": {
            "gl_account_debit": "Prepaid Expenses",
            "gl_account_credit": "Accounts Payable",
            "standard_cited": "IFRS 15",
            "paragraph_cited": "Para 31",
        },
        "fraud": {
            "risk_score": 8,
            "tier": "clean",
            "llm_result": {"top_3_signals": [], "reasoning": "Clean invoice."},
        },
        "verifier": {
            "verdict": "APPROVED",
            "final_confidence": 0.95,
            "passed_count": 3,
        },
        "verdict": "APPROVED",
        "final_confidence": 0.95,
    }
    print(json.dumps(explain(demo_pipeline), indent=2))
