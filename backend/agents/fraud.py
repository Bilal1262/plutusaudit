"""
Agent 3 - Fraud & Anomaly Detector.

Two-stage design (THIS IS CRITICAL):

Stage 1: 9 deterministic signals (pure Python, no API calls).
Stage 2: Featherless Qwen3-32B reasons over the signals to produce a
         calibrated 0-100 risk score, tier, and natural-language explanation.

The deterministic signals are always returned alongside the LLM result so
the FraudHeatmap UI can render individual signal states.

Research basis: Nigrini (1999) Benford's Law for fraud detection,
USPTO patents 12,045,215 and 12,106,384 (duplicate / near-duplicate
invoice detection).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import config

logger = logging.getLogger(__name__)


# ── prompt + Featherless client ────────────────────────────────────────────────
_PROMPT_PATH = config.PROMPTS_DIR / "fraud.txt"
_featherless_client = None


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _get_featherless_client():
    global _featherless_client
    if _featherless_client is not None:
        return _featherless_client
    from openai import OpenAI

    if not config.FEATHERLESS_API_KEY:
        raise RuntimeError("FEATHERLESS_API_KEY is not set.")
    _featherless_client = OpenAI(
        base_url=config.FEATHERLESS_BASE_URL,
        api_key=config.FEATHERLESS_API_KEY,
    )
    return _featherless_client


# ── vendor history loader (cached) ─────────────────────────────────────────────
_vendor_history: Optional[dict] = None


def _load_vendor_history() -> dict:
    global _vendor_history
    if _vendor_history is not None:
        return _vendor_history
    p = Path(config.VENDOR_HISTORY_PATH)
    if not p.exists():
        _vendor_history = {}
        return _vendor_history
    _vendor_history = json.loads(p.read_text(encoding="utf-8"))
    return _vendor_history


# ── deterministic signal helpers ───────────────────────────────────────────────
def _benford_mad(amounts: list[float]) -> Optional[float]:
    """
    Mean Absolute Deviation of leading-digit distribution from Benford.

    Returns None if there isn't enough data (< 30 invoices).
    A vendor's history with MAD > 0.015 is suspicious (Nigrini).
    """
    if len(amounts) < 30:
        return None

    expected = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
    counts = {d: 0 for d in range(1, 10)}
    total = 0

    for amt in amounts:
        if amt <= 0:
            continue
        first = int(str(amt).lstrip("0.").replace(".", "")[0:1] or "0")
        if 1 <= first <= 9:
            counts[first] += 1
            total += 1

    if total == 0:
        return None

    observed = {d: counts[d] / total for d in range(1, 10)}
    mad = sum(abs(observed[d] - expected[d]) for d in range(1, 10)) / 9.0
    return round(mad, 5)


def _levenshtein(a: str, b: str) -> int:
    try:
        import Levenshtein

        return Levenshtein.distance(a, b)
    except Exception:  # noqa: BLE001
        # Pure-python fallback
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i] + [0] * len(b)
            for j, cb in enumerate(b, 1):
                cur[j] = min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            prev = cur
        return prev[-1]


def _is_below_threshold(amount: float) -> bool:
    """True if amount lies within the configured margin BELOW any approval level."""
    if amount <= 0:
        return False
    for thr in config.APPROVAL_THRESHOLDS:
        low = thr * (1 - config.BELOW_THRESHOLD_MARGIN)
        if low <= amount < thr:
            return True
    return False


def check_invoice_splitting_pattern(
    invoice: dict,
    db: Optional[Session],
    *,
    invoice_id: Optional[str],
) -> dict:
    """
    Histories invoices from the same vendor sitting just below a common PO/approval tier
    (classic splitting / structuring to avoid approvals).
    """
    out: dict[str, Any] = {"splitting_pattern": False}
    if db is None:
        return out

    vendor_raw = (invoice.get("vendor_name") or "").strip()
    if not vendor_raw:
        return out

    try:
        current_amount = float(invoice.get("grand_total") or 0)
    except (TypeError, ValueError):
        return out

    near_thr: Optional[float] = None
    for thr in config.APPROVAL_THRESHOLDS:
        low = thr * (1 - config.BELOW_THRESHOLD_MARGIN)
        if low <= current_amount < thr:
            near_thr = float(thr)
            break

    if near_thr is None:
        return out

    try:
        from backend.db.models import Invoice as InvoiceModel

        cutoff = datetime.utcnow() - timedelta(days=30)
        vendor_lc = vendor_raw.lower()

        base_q = (
            db.query(InvoiceModel)
            .filter(
                InvoiceModel.created_at >= cutoff,
                InvoiceModel.grand_total.isnot(None),
                InvoiceModel.vendor_name.isnot(None),
                func.lower(InvoiceModel.vendor_name) == vendor_lc,
                InvoiceModel.grand_total > near_thr * (1 - config.BELOW_THRESHOLD_MARGIN),
                InvoiceModel.grand_total < near_thr,
            )
        )
        if invoice_id:
            base_q = base_q.filter(InvoiceModel.id != invoice_id)

        prior_count = base_q.count()
        if prior_count >= 2:
            count = prior_count + 1
            ccy = (invoice.get("currency") or "").strip().upper() or "USD"
            sym = "£" if ccy == "GBP" else "€" if ccy == "EUR" else "$"
            thr_int = int(near_thr) if near_thr == int(near_thr) else near_thr
            desc = (
                f"{count} invoices from {vendor_raw} all just under the "
                f"{sym}{thr_int:,} approval band in the last 30 days"
            )
            return {
                "splitting_pattern": True,
                "count": count,
                "threshold": near_thr,
                "description": desc,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("invoice splitting history check failed: %s", exc)

    return out


def _is_round_number(amount: float) -> bool:
    if amount <= 0:
        return False
    return (amount % 500 == 0) or (amount % 1000 == 0)


def _vague_description(items: list[dict]) -> bool:
    for li in items:
        desc = (li.get("description") or "").strip().lower()
        if not desc:
            return True
        words = [w for w in desc.split() if w.isalpha()]
        if len(words) <= 2:
            return True
        if any(w in config.VAGUE_WORDS for w in words):
            # Only fire if EVERY meaningful word is vague (avoid false positives)
            non_vague = [w for w in words if w not in config.VAGUE_WORDS]
            if not non_vague:
                return True
    return False


def _off_hours(received_at: Optional[str]) -> bool:
    if not received_at:
        return False
    try:
        dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    hour = dt.hour
    return hour < 7 or hour > 20


# ── DB-based checks ────────────────────────────────────────────────────────────
def _check_exact_duplicate(
    db: Optional[Session], invoice: dict, *, invoice_id: Optional[str] = None
) -> bool:
    if db is None:
        return False
    vendor = invoice.get("vendor_name")
    inv_num = invoice.get("invoice_number")
    amount = invoice.get("grand_total")
    # Guard against low-quality extraction defaults causing false positives
    if not vendor or not inv_num or amount in (None, 0, 0.0):
        return False
    try:
        from backend.db.models import Invoice as InvoiceModel

        q = db.query(InvoiceModel).filter_by(
            vendor_name=vendor,
            invoice_number=inv_num,
        )
        if invoice_id:
            q = q.filter(InvoiceModel.id != invoice_id)
        return q.first() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("exact_duplicate db check failed: %s", exc)
        return False


def _check_near_duplicates(
    db: Optional[Session], invoice: dict, *, invoice_id: Optional[str] = None
) -> int:
    """Same vendor, amount within +/- 1%, inv_num within Levenshtein 3."""
    if db is None:
        return 0
    try:
        from backend.db.models import Invoice as InvoiceModel

        vendor = invoice.get("vendor_name")
        amount = float(invoice.get("grand_total") or 0)
        inv_num = str(invoice.get("invoice_number") or "")
        if not vendor or amount == 0:
            return 0

        low, high = amount * 0.99, amount * 1.01
        candidates = (
            db.query(InvoiceModel)
            .filter(InvoiceModel.vendor_name == vendor)
            .filter(InvoiceModel.grand_total >= low)
            .filter(InvoiceModel.grand_total <= high)
            .filter(InvoiceModel.id != invoice_id if invoice_id else True)
            .all()
        )
        count = 0
        for c in candidates:
            if c.invoice_number and _levenshtein(inv_num, str(c.invoice_number)) <= 3:
                count += 1
        return count
    except Exception as exc:  # noqa: BLE001
        logger.warning("near_duplicate db check failed: %s", exc)
        return 0


def _check_new_vendor(db: Optional[Session], invoice: dict) -> bool:
    """Vendor not in approved-vendor list (or non-existent)."""
    if db is None:
        return True
    try:
        from backend.db.models import Vendor

        name = (invoice.get("vendor_name") or "").upper().replace(" ", "_")
        candidates = db.query(Vendor).all()
        for v in candidates:
            if v.name.upper() == name and v.is_approved:
                return False
            if v.name.upper().replace("_", "") in name.replace("_", ""):
                return not v.is_approved
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("new_vendor db check failed: %s", exc)
        return False


# ── Stage 1: compute all 9 signals ─────────────────────────────────────────────
def compute_signals(
    invoice: dict,
    *,
    db: Optional[Session] = None,
    invoice_id: Optional[str] = None,
) -> dict:
    amount = float(invoice.get("grand_total") or 0)
    vendor = invoice.get("vendor_name") or ""

    # Benford
    history = _load_vendor_history()
    history_amounts: list[float] = []
    vendor_key = vendor.upper().replace(" ", "_")
    if vendor_key in history:
        history_amounts = [r["amount"] for r in history[vendor_key]]
    elif vendor in history:
        history_amounts = [r["amount"] for r in history[vendor]]
    benford_mad = _benford_mad(history_amounts)
    benford_flag = bool(
        benford_mad is not None and benford_mad > config.BENFORD_MAD_THRESHOLD
    )

    return {
        "exact_duplicate": _check_exact_duplicate(db, invoice, invoice_id=invoice_id),
        "near_duplicate_count": _check_near_duplicates(
            db, invoice, invoice_id=invoice_id
        ),
        "benford_flag": benford_flag,
        "benford_mad": benford_mad,
        "round_number": _is_round_number(amount),
        "below_threshold": _is_below_threshold(amount),
        "missing_po": (
            invoice.get("po_number") in (None, "", "null") and amount > 1000
        ),
        "vague_description": _vague_description(invoice.get("line_items") or []),
        "new_vendor": _check_new_vendor(db, invoice),
        "off_hours_submission": _off_hours(invoice.get("received_at")),
        "bank_account_change_requested": bool(
            invoice.get("bank_account_change_requested")
        ),
        "vendor_history_count": len(history_amounts),
    }


# ── Stage 2: Featherless reasoning ─────────────────────────────────────────────
def _safe_json_loads(s: str) -> dict:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise


def _heuristic_score(signals: dict) -> dict:
    """
    Fallback when Featherless is unavailable. Pure-Python score using the
    rubric anchors. Keeps the demo functional offline.
    """
    score = 0
    fired: list[str] = []
    if signals.get("exact_duplicate"):
        score += 60
        fired.append("exact_duplicate")
    if signals.get("near_duplicate_count", 0) >= 1:
        score += 35
        fired.append("near_duplicate_count")
    if signals.get("benford_flag"):
        score += 20
        fired.append("benford_flag")
    if signals.get("round_number"):
        score += 12
        fired.append("round_number")
    if signals.get("below_threshold"):
        score += 18
        fired.append("below_threshold")
    if signals.get("missing_po"):
        score += 10
        fired.append("missing_po")
    if signals.get("vague_description"):
        score += 12
        fired.append("vague_description")
    if signals.get("new_vendor"):
        score += 15
        fired.append("new_vendor")
    if signals.get("off_hours_submission"):
        score += 8
        fired.append("off_hours_submission")
    if signals.get("bank_account_change_requested"):
        score += 25
        fired.append("bank_account_change_requested")

    # Interaction bonuses
    if (
        signals.get("new_vendor")
        and signals.get("below_threshold")
        and signals.get("vague_description")
    ):
        score += 15
    if signals.get("near_duplicate_count", 0) >= 1:
        score += 10
    if signals.get("bank_account_change_requested") and signals.get("new_vendor"):
        score += 25
    if signals.get("invoice_splitting_sequence"):
        score = max(score, 76)
        if "invoice_splitting_sequence" not in fired:
            fired.append("invoice_splitting_sequence")

    # Deterministic floors: binary duplicate evidence is not discretionary.
    if signals.get("near_duplicate_count", 0) >= 1 and signals.get("missing_po"):
        score = max(score, 50)
    if signals.get("exact_duplicate"):
        score = max(score, 70)
    if signals.get("exact_duplicate") and signals.get("missing_po"):
        score = max(score, 85)

    score = min(100, score)
    tier = _tier_for_score(score)

    return {
        "reasoning": (
            f"Heuristic fallback (Featherless unavailable). Fired signals: "
            f"{', '.join(fired) or 'none'}. Tier {tier} at score {score}."
        ),
        "risk_score": score,
        "tier": tier,
        "top_3_signals": fired[:3],
        "plain_english_explanation": (
            f"This invoice scored {score}/100 based on {len(fired)} deterministic "
            f"signal(s). Recommended action: "
            + ("auto-pay." if tier == "clean" else "review by AP manager." if tier == "review" else "block and escalate.")
        ),
        "recommended_action": (
            _recommended_action_for_tier(tier)
        ),
        "source": "heuristic_fallback",
    }


def _fired_signal_names(signals: dict) -> list[str]:
    fired: list[str] = []
    for key, value in signals.items():
        if key.startswith("_"):
            continue
        if key in {"benford_mad", "vendor_history_count"}:
            continue
        if value is True:
            fired.append(key)
        elif key == "near_duplicate_count" and int(value or 0) > 0:
            fired.append(key)
    return fired


def _tier_for_score(score: int) -> str:
    if score >= config.FRAUD_BLOCK_THRESHOLD:
        return "block"
    if score >= config.FRAUD_REVIEW_THRESHOLD:
        return "review"
    return "clean"


def _recommended_action_for_tier(tier: str) -> str:
    if tier == "block":
        return "block and escalate to controller"
    if tier == "review":
        return "route to AP manager"
    return "auto-pay"


def _apply_signal_floor(llm_result: dict, signals: dict) -> dict:
    """
    Deterministic controls are authoritative enough to set a minimum score.
    If an LLM under-scores fired signals, preserve its reasoning but raise score.
    """
    fired = _fired_signal_names(signals)
    if not fired:
        return llm_result

    try:
        risk_score = int(llm_result.get("risk_score", 0) or 0)
    except (TypeError, ValueError):
        risk_score = 0

    signal_floor = len(fired) * 10
    forced_tier: str | None = None
    guard_warnings: list[str] = []

    if signals.get("missing_po") and signals.get("new_vendor"):
        signal_floor = max(signal_floor, config.FRAUD_REVIEW_THRESHOLD)

    if (
        signals.get("round_number")
        and signals.get("missing_po")
        and signals.get("new_vendor")
    ):
        signal_floor = max(signal_floor, 60)
        if forced_tier != "block":
            forced_tier = "review"
        guard_warnings.append("round_number_missing_po_new_vendor_floor_applied")

    if signals.get("near_duplicate_count", 0) >= 1 and signals.get("missing_po"):
        signal_floor = max(signal_floor, 50)
        if _tier_for_score(risk_score) == "clean":
            forced_tier = "review"
        guard_warnings.append("near_duplicate_missing_po_floor_applied")

    if signals.get("exact_duplicate"):
        signal_floor = max(signal_floor, 70)
        forced_tier = "block"
        guard_warnings.append("exact_duplicate_floor_applied")

    if signals.get("exact_duplicate") and signals.get("missing_po"):
        signal_floor = max(signal_floor, 85)
        forced_tier = "block"
        guard_warnings.append("exact_duplicate_missing_po_floor_applied")

    if signals.get("below_threshold") and signals.get("missing_po"):
        signal_floor = max(signal_floor, 45)
        guard_warnings.append("invoice_splitting_pattern_floor_applied")
        if signals.get("new_vendor"):
            signal_floor = max(signal_floor, 55)
            guard_warnings.append("invoice_splitting_new_vendor_review_floor_applied")
            if forced_tier != "block":
                forced_tier = "review"

    if signals.get("invoice_splitting_sequence"):
        detail = signals.get("_invoice_splitting_detail") or {}
        signal_floor = max(signal_floor, 75)
        forced_tier = "block"
        guard_warnings.append("invoice_splitting_history_block_floor_applied")
        desc = str(detail.get("description") or "").strip()
        if desc:
            prefix = (
                "CRITICAL: repeated sub-threshold invoices from this vendor near the "
                f"same approval band — invoice splitting risk. {desc}. "
            )
            llm_result["plain_english_explanation"] = (
                prefix + str(llm_result.get("plain_english_explanation") or "").strip()
            ).strip()

    final_score = max(risk_score, signal_floor)
    final_tier = forced_tier or _tier_for_score(final_score)

    floor_changed = risk_score < signal_floor
    tier_changed = llm_result.get("tier") != final_tier

    if floor_changed or tier_changed or guard_warnings:
        llm_result["risk_score"] = final_score
        llm_result["tier"] = final_tier
        llm_result["recommended_action"] = _recommended_action_for_tier(final_tier)
        existing = llm_result.get("top_3_signals") or []
        llm_result["top_3_signals"] = list(dict.fromkeys([*existing, *fired]))[:3]
        llm_result.setdefault(
            "plain_english_explanation",
            (
                f"This invoice scored {final_score}/100 after deterministic "
                f"control flooring for fired signal(s): {', '.join(fired)}."
            ),
        )
        warnings = llm_result.setdefault("guard_warnings", [])
        if floor_changed:
            warnings.append(
                f"risk_score_floor_applied_from_{risk_score}_to_{final_score}"
            )
        for warning in guard_warnings:
            if warning not in warnings:
                warnings.append(warning)
    return llm_result


def llm_reason_over_signals(invoice: dict, signals: dict) -> dict:
    """Call Featherless Qwen3-32B; fall back to heuristic on any error."""
    try:
        client = _get_featherless_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Featherless unavailable: %s", exc)
        return _heuristic_score(signals)

    prompt = _load_prompt()
    public_signals = {k: v for k, v in signals.items() if not str(k).startswith("_")}
    user_msg = (
        f"INVOICE:\n{json.dumps(invoice, default=str, indent=2)}\n\n"
        f"DETERMINISTIC_SIGNALS:\n{json.dumps(public_signals, default=str, indent=2)}\n\n"
        "Reason carefully about signal interactions, then output the JSON."
    )

    try:
        resp = client.chat.completions.create(
            model=config.FEATHERLESS_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=900,
        )
        text = resp.choices[0].message.content or ""
        parsed = _safe_json_loads(text)
        # Validate response shape; some models emit non-object-like wrappers
        # such as {"_type":"set","content":[...]} which are unusable here.
        if not isinstance(parsed, dict):
            logger.warning("Featherless returned non-dict JSON; using heuristic fallback.")
            return _heuristic_score(signals)
        if "_type" in parsed and "risk_score" not in parsed:
            logger.warning(
                "Featherless returned wrapper JSON (%s); using heuristic fallback.",
                parsed.get("_type"),
            )
            return _heuristic_score(signals)

        parsed["source"] = "featherless_qwen3_32b"
        # Clamp + normalise
        try:
            parsed["risk_score"] = max(0, min(100, int(parsed.get("risk_score", 0))))
        except (TypeError, ValueError):
            logger.warning("Featherless response missing valid risk_score; using heuristic fallback.")
            return _heuristic_score(signals)

        parsed["tier"] = _tier_for_score(parsed["risk_score"])
        return _apply_signal_floor(parsed, signals)
    except Exception as exc:  # noqa: BLE001
        logger.error("Featherless call failed: %s. Using heuristic fallback.", exc)
        return _heuristic_score(signals)


# ── public entry point ────────────────────────────────────────────────────────
def detect_fraud(
    invoice: dict,
    *,
    db: Optional[Session] = None,
    invoice_id: Optional[str] = None,
) -> dict:
    """
    Full two-stage fraud detection.

    Returns:
        {
            "signals": {...individual deterministic signals...},
            "llm_result": {...Featherless reasoning + risk score...},
            "risk_score": int,
            "tier": str,
        }
    """
    signals = compute_signals(invoice, db=db, invoice_id=invoice_id)

    splitting = check_invoice_splitting_pattern(invoice, db, invoice_id=invoice_id)
    signals["invoice_splitting_sequence"] = bool(splitting.get("splitting_pattern"))
    signals["_invoice_splitting_detail"] = splitting

    llm_result = llm_reason_over_signals(invoice, signals)
    llm_result = _apply_signal_floor(llm_result, signals)

    result = {
        "signals": signals,
        "llm_result": llm_result,
        "risk_score": llm_result.get("risk_score", 0),
        "tier": llm_result.get("tier", "clean"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    if db is not None and invoice_id:
        try:
            from backend.db.models import Invoice as InvoiceModel

            db.query(InvoiceModel).filter(InvoiceModel.id == invoice_id).update(
                {
                    "fraud_score": int(result["risk_score"] or 0),
                    "fraud_tier": result["tier"],
                    "status": "blocked" if result["tier"] == "block" else "flagged",
                }
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist fraud score/tier for invoice %s: %s", invoice_id, exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return result


# ── smoke test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample = {
        "vendor_name": "FASTCONSULT",
        "invoice_number": "FC-99812",
        "po_number": None,
        "currency": "USD",
        "grand_total": 4950.00,
        "line_items": [{"description": "Consulting services"}],
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    out = detect_fraud(sample)
    print(json.dumps(out, indent=2, default=str))
