"""
Agent 4 - Verifier + Hallucination Guard.

Three aspect verifiers run in sequence:

    V1: Numerical Consistency   (pure-Python; debit == credit, amount == grand_total)
    V2: Citation Grounding      (Gemini; is the cited paragraph in the retrieved context?)
    V3: Schema Conformance      (Gemini; GL accounts valid, deferral consistent, review flag correct)

Voting:
    3/3 pass -> APPROVED          (confidence 0.95)
    2/3 pass -> APPROVED_WITH_WARNING (confidence 0.75; dissenter logged)
    <2/3    -> RETRY              (build critique, call Accountant again)
                                  After VERIFIER_MAX_RETRIES, ESCALATED.

Research basis: Multi-Agent Verification (Lifshitz & Du, arXiv:2502.20379).
"""

from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable, Optional

from backend import config
from backend.agents.accountant import classify_invoice
from backend.agents.doc_intel import _get_gemini_model, _safe_json_loads

logger = logging.getLogger(__name__)


# ── prompt loaders ────────────────────────────────────────────────────────────
_PROMPT_DIR = config.PROMPTS_DIR


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


# ── V1: Numerical Consistency (deterministic) ─────────────────────────────────
def verify_numerical(invoice: dict, accountant: dict) -> dict:
    violations: list[str] = []
    deltas: list[float] = []

    try:
        gt = float(invoice.get("grand_total") or 0.0)
    except (TypeError, ValueError):
        gt = 0.0

    try:
        amt = float(accountant.get("amount") or 0.0)
    except (TypeError, ValueError):
        amt = 0.0

    # In a single-line journal entry, the same amount appears as both debit and
    # credit. Accountant.amount is treated as both sides.
    debit = amt
    credit = amt

    if abs(debit - credit) > 0.01:
        violations.append(f"debit {debit:.2f} != credit {credit:.2f}")
        deltas.append(abs(debit - credit))

    if gt > 0 and abs(amt - gt) > 0.01:
        violations.append(
            f"journal_amount {amt:.2f} != invoice.grand_total {gt:.2f}"
        )
        deltas.append(abs(amt - gt))

    return {
        "verifier": "numerical",
        "passed": len(violations) == 0,
        "delta": max(deltas) if deltas else 0.0,
        "violations": violations,
        "confidence": 1.0 if not violations else 0.0,
    }


# ── V2: Citation Grounding (Gemini) ───────────────────────────────────────────
def verify_citation(accountant: dict) -> dict:
    chunks = accountant.get("retrieved_chunks") or []
    cited_std = accountant.get("standard_cited", "")
    cited_par = accountant.get("paragraph_cited", "")

    if not chunks:
        return {
            "verifier": "citation",
            "passed": False,
            "evidence": "",
            "violations": ["no_retrieved_chunks_available"],
            "confidence": 0.0,
        }

    context_block = "\n\n".join(
        f"[{c['standard']} Para {c['paragraph']}] {c['topic']}\n{c['rule']}"
        for c in chunks
    )

    prompt = _load_prompt("verifier_citation.txt")
    user_msg = (
        f"CITED_STANDARD: {cited_std}\n"
        f"CITED_PARAGRAPH: {cited_par}\n\n"
        f"ACCOUNTANT_REASONING:\n{accountant.get('reasoning','')}\n\n"
        f"RETRIEVED_CONTEXT:\n{context_block}\n"
    )

    try:
        model = _get_gemini_model()
        resp = model.generate_content([prompt, user_msg])
        parsed = _safe_json_loads((getattr(resp, "text", None) or "").strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("verifier_citation: gemini failed -> falling back to deterministic check (%s)", exc)
        # Deterministic fallback - identical to accountant's faithfulness guard
        std_norm = cited_std.strip().lower().replace(" ", "")
        par_norm = (
            cited_par.strip().lower().replace(" ", "").replace("para", "")
        )
        match = next(
            (
                c
                for c in chunks
                if std_norm in c["standard"].strip().lower().replace(" ", "")
                and par_norm
                == c["paragraph"]
                .strip()
                .lower()
                .replace(" ", "")
                .replace("para", "")
            ),
            None,
        )
        return {
            "verifier": "citation",
            "passed": bool(match),
            "evidence": (match["rule"][:200] + "...") if match else "",
            "violations": [] if match else ["cited paragraph not present in retrieved context"],
            "confidence": 1.0 if match else 0.0,
            "source": "deterministic_fallback",
        }

    return {
        "verifier": "citation",
        "passed": bool(parsed.get("passed")),
        "evidence": parsed.get("evidence", ""),
        "violations": parsed.get("violations", []) or [],
        "confidence": 1.0 if parsed.get("passed") else 0.0,
        "source": "gemini",
    }


# ── V3: Schema Conformance (Gemini, with deterministic fallback) ─────────────
def verify_schema(accountant: dict) -> dict:
    violations: list[str] = []

    debit = accountant.get("gl_account_debit", "")
    credit = accountant.get("gl_account_credit", "")
    chart = config.CHART_OF_ACCOUNTS

    # Deterministic pre-checks (these run even if Gemini fails)
    if debit not in chart:
        violations.append(f"gl_account_debit '{debit}' not in chart of accounts")
    if credit not in chart:
        violations.append(f"gl_account_credit '{credit}' not in chart of accounts")

    deferral = bool(accountant.get("deferral_required"))
    has_schedule = bool(accountant.get("amortization_schedule"))
    is_prepaid_like = (
        debit.startswith("Prepaid")
        or debit in {"Right-of-Use Asset", "Intangible Assets - Software"}
    )
    if deferral and not (is_prepaid_like or has_schedule):
        violations.append(
            "deferral_required=true but debit account is not a prepaid/asset and no amortization_schedule provided"
        )

    confidence = float(accountant.get("confidence", 0.0) or 0.0)
    requires_review = bool(accountant.get("requires_human_review"))
    if confidence < config.CONFIDENCE_HUMAN_REVIEW_THRESHOLD and not requires_review:
        violations.append(
            f"confidence={confidence:.2f} below threshold {config.CONFIDENCE_HUMAN_REVIEW_THRESHOLD} but requires_human_review=false"
        )

    if not accountant.get("standard_cited") or accountant.get("standard_cited") == "Unknown":
        violations.append("standard_cited is empty or 'Unknown'")
    if not accountant.get("paragraph_cited") or accountant.get("paragraph_cited") == "Unknown":
        violations.append("paragraph_cited is empty or 'Unknown'")

    # Optionally let Gemini add nuance (skip if we have no key)
    gemini_extra: list[str] = []
    try:
        model = _get_gemini_model()
        prompt = _load_prompt("verifier_schema.txt")
        user_msg = (
            f"CHART_OF_ACCOUNTS:\n{json.dumps(chart)}\n\n"
            f"ACCOUNTANT_OUTPUT:\n{json.dumps(accountant, default=str, indent=2)}\n"
        )
        resp = model.generate_content([prompt, user_msg])
        parsed = _safe_json_loads((getattr(resp, "text", None) or "").strip())
        gemini_extra = parsed.get("violations", []) or []
    except Exception as exc:  # noqa: BLE001
        logger.info("verifier_schema: gemini check skipped (%s) - using deterministic only", exc)

    all_violations = violations + [v for v in gemini_extra if v not in violations]
    return {
        "verifier": "schema",
        "passed": len(all_violations) == 0,
        "violations": all_violations,
        "confidence": 1.0 if not all_violations else 0.0,
    }


# ── orchestration ─────────────────────────────────────────────────────────────
def _build_critique(failed_verifiers: list[dict]) -> str:
    bullets = []
    for v in failed_verifiers:
        for violation in v.get("violations", []):
            bullets.append(f"  - ({v['verifier']}) {violation}")
    return (
        "Your previous classification failed verification. Issues:\n"
        + "\n".join(bullets)
        + "\n\nRe-do the task correcting EACH issue above."
    )


async def _emit(
    on_event: Optional[Callable[[dict], Awaitable[None]]], payload: dict
) -> None:
    if on_event is not None:
        try:
            await on_event(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("verifier on_event hook failed: %s", exc)


async def verify_and_retry(
    invoice: dict,
    accountant_output: dict,
    *,
    on_event: Optional[Callable[[dict], Awaitable[None]]] = None,
    max_retries: int = config.VERIFIER_MAX_RETRIES,
) -> dict:
    """
    Run the 3 verifiers; on failure, retry the Accountant with a critique.

    `on_event` is an async callback used by main.py to emit SSE updates
    when a retry is triggered.
    """
    attempt = 1
    current = accountant_output
    history: list[dict] = []

    while True:
        v1 = verify_numerical(invoice, current)
        v2 = verify_citation(current)
        v3 = verify_schema(current)
        votes = [v1, v2, v3]
        passed = sum(1 for v in votes if v["passed"])

        history.append({"attempt": attempt, "votes": votes})

        if passed == 3:
            verdict = "APPROVED"
            final_conf = 0.95
            critique = None
            break

        if passed == 2:
            verdict = "APPROVED_WITH_WARNING"
            final_conf = 0.75
            critique = None
            break

        # Need to retry
        failed = [v for v in votes if not v["passed"]]
        critique = _build_critique(failed)

        if attempt > max_retries:
            verdict = "ESCALATED"
            final_conf = 0.40
            break

        # Emit "retrying" SSE event with the critique
        await _emit(
            on_event,
            {
                "agent": "verifier",
                "status": "retrying",
                "attempt": attempt,
                "data": {
                    "votes": votes,
                    "critique": critique,
                },
            },
        )

        # Call accountant again with the critique injected
        attempt += 1
        current = classify_invoice(invoice, extra_critique=critique)

    return {
        "verdict": verdict,
        "final_confidence": final_conf,
        "passed_count": passed,
        "verifier_votes": votes,
        "history": history,
        "attempt": attempt,
        "critique": critique,
        "accountant_output": current,
    }


# ── smoke test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    sample_invoice = {
        "vendor_name": "Acme Software",
        "grand_total": 2400.00,
    }
    sample_accountant = {
        "reasoning": "12-month SaaS subscription. Defer per IFRS 15 Para 31.",
        "gl_account_debit": "Prepaid Expenses",
        "gl_account_credit": "Accounts Payable",
        "amount": 2400.00,
        "standard_cited": "IFRS 15",
        "paragraph_cited": "Para 31",
        "deferral_required": True,
        "amortization_schedule": {
            "monthly_amount": 200,
            "months": 12,
            "monthly_debit": "Subscription Expense",
            "monthly_credit": "Prepaid Expenses",
        },
        "confidence": 0.9,
        "requires_human_review": False,
        "retrieved_chunks": [
            {
                "id": "demo",
                "standard": "IFRS 15",
                "paragraph": "31",
                "topic": "Software Subscriptions",
                "rule": "Defer prepaid SaaS over the subscription term.",
            }
        ],
    }
    out = asyncio.run(verify_and_retry(sample_invoice, sample_accountant))
    print(json.dumps({k: v for k, v in out.items() if k != "accountant_output"}, indent=2, default=str))
