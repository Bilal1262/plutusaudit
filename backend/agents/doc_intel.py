"""
Agent 1 - Document Intelligence (multimodal OCR).

Pipeline:
    1) Try pdfplumber for an embedded text layer (fast, free).
    2) If text is too short / unhelpful, rasterise PDF page 1 with pdf2image.
    3) Call Gemini 2.5 Flash with response_mime_type="application/json".
    4) Arithmetic guard: subtotal + tax ~= grand_total.
    5) Return a structured dict with extraction_confidence and warnings.

Research basis: Berghaus et al. arXiv:2509.04469 — native multimodal models
beat OCR pipelines on invoice extraction.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend import config

logger = logging.getLogger(__name__)
VAT_PATTERN = re.compile(r"^(VAT:|GB\d|DE\d|FR\d|\d{8,})", re.IGNORECASE)
REDACTED_VENDOR_PATTERNS = {None, "", "[REDACTED]", "Unknown", "N/A"}
MINIMUM_VIABLE_EXTRACTION = {
    "grand_total": lambda x: x is not None and float(x) > 0,
    "invoice_number": lambda x: x not in (None, "", "Unknown", "N/A"),
    "invoice_date": lambda x: x not in (None, "", "Unknown", "N/A"),
}


# ── prompt loader (cached) ─────────────────────────────────────────────────────
_PROMPT_PATH = config.PROMPTS_DIR / "doc_intel.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ── lazy Gemini client ─────────────────────────────────────────────────────────
_genai_client = None
_genai_model = None


def _get_gemini_model():
    global _genai_client, _genai_model
    if _genai_model is not None:
        return _genai_model

    import google.generativeai as genai

    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Cannot call Gemini.")
    genai.configure(api_key=config.GEMINI_API_KEY)

    _genai_client = genai
    _genai_model = genai.GenerativeModel(
        config.GEMINI_MODEL,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.1,
        },
    )
    return _genai_model


# ── PDF helpers ────────────────────────────────────────────────────────────────
def _try_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n".join(pages).strip()
            logger.info(
                "doc_intel: pdfplumber extracted chars=%d preview=%r",
                len(text),
                text[:200],
            )
            return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber text extraction failed: %s", exc)
        return ""


def _pdf_to_png_bytes(pdf_bytes: bytes, dpi: int = 150) -> Optional[bytes]:
    try:
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(pdf_bytes, dpi=dpi, first_page=1, last_page=1)
        if not images:
            return None
        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdf2image rasterisation failed: %s", exc)
        return None


def _resize_if_needed(img_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    """Keep Gemini image payloads comfortably below API size limits."""
    max_bytes = 3 * 1024 * 1024
    if len(img_bytes) <= max_bytes:
        return img_bytes, mime_type

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(img_bytes))
        scale = 0.8
        resized_bytes = img_bytes
        while len(resized_bytes) > max_bytes and scale > 0.2:
            new_w = max(1, int(img.width * scale))
            new_h = max(1, int(img.height * scale))
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            resized.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
            resized_bytes = buf.getvalue()
            scale -= 0.1

        logger.info(
            "doc_intel: resized image for Gemini from %d to %d bytes",
            len(img_bytes),
            len(resized_bytes),
        )
        return resized_bytes, "image/jpeg"
    except Exception as exc:  # noqa: BLE001
        logger.warning("image resize failed; using original image bytes: %s", exc)
        return img_bytes, mime_type


def _get_image_bytes_and_mime(file_bytes: bytes, filename: str) -> tuple[Optional[bytes], str]:
    """
    Prepare visual input for Gemini using magic bytes, not filename extension.
    PDFs are rasterized to PNG; JPEG/PNG are sent with their real MIME type.
    """
    try:
        if file_bytes[:4] == b"%PDF":
            img_bytes = _pdf_to_png_bytes(file_bytes)
            if img_bytes is None:
                return None, "image/png"
            mime_type = "image/png"
        elif file_bytes[:2] == b"\xff\xd8":
            img_bytes = file_bytes
            mime_type = "image/jpeg"
        elif file_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            img_bytes = file_bytes
            mime_type = "image/png"
        elif file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
            img_bytes = file_bytes
            mime_type = "image/webp"
        else:
            from PIL import Image

            img = Image.open(io.BytesIO(file_bytes))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
            mime_type = "image/png"

        img_bytes, mime_type = _resize_if_needed(img_bytes, mime_type)
        logger.info(
            "doc_intel: prepared image for Gemini filename=%s mime=%s bytes=%d",
            filename,
            mime_type,
            len(img_bytes),
        )
        return img_bytes, mime_type
    except Exception as exc:  # noqa: BLE001
        logger.warning("image preparation failed for %s: %s", filename, exc)
        return None, "image/png"


# ── core extraction ────────────────────────────────────────────────────────────
def _has_good_text_layer(text: str) -> bool:
    """
    Strong quality gate for text-layer extraction.
    Scanned PDFs can contain OCR artifacts/watermarks that pass simple length checks.
    """
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < 200:
        return False

    tl = stripped.lower()
    keywords = [
        "invoice",
        "total",
        "amount",
        "date",
        "vendor",
        "bill",
        "payment",
        "vat",
        "tax",
        "due",
        "subtotal",
        "£",
        "$",
        "€",
    ]
    keyword_hits = sum(1 for kw in keywords if kw in tl)
    if keyword_hits < 3:
        return False

    # Require at least one amount-like numeric token.
    amounts = re.findall(r"\d[\d,.\s]{2,}\d", stripped)
    if not amounts:
        return False

    return True


def _build_extraction_request(
    text_content: Optional[str],
    image_bytes: Optional[bytes],
    image_mime_type: str = "image/png",
) -> list:
    """Build the prompt+content list for Gemini multimodal."""
    prompt = _load_prompt()
    parts: list[Any] = [prompt]

    if text_content:
        parts.append("\n\n=== INVOICE TEXT CONTENT ===\n" + text_content)
    if image_bytes:
        # IMPORTANT: for PDFs we only pass rasterized image bytes, never raw PDF bytes.
        parts.append({"mime_type": image_mime_type, "data": image_bytes})
    return parts


def _safe_json_loads(s: str) -> dict:
    """Robust JSON parser - strips ```json``` fences if Gemini ignored the instruction."""
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Try to find the first { ... } block
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise


# ── arithmetic guard ───────────────────────────────────────────────────────────
def _arithmetic_check(result: dict) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    items = result.get("line_items") or []
    subtotal = result.get("subtotal")
    tax = result.get("tax_amount")
    grand = result.get("grand_total")

    try:
        if items:
            lines_sum = round(sum(float(li.get("line_total") or 0) for li in items), 2)
            if subtotal is not None and abs(lines_sum - float(subtotal)) > 0.05:
                warnings.append(
                    f"line_items sum {lines_sum:.2f} != subtotal {float(subtotal):.2f}"
                )

        if subtotal is not None and grand is not None:
            implied = round(float(subtotal) + float(tax or 0), 2)
            if abs(implied - float(grand)) > 0.05:
                warnings.append(
                    f"subtotal+tax {implied:.2f} != grand_total {float(grand):.2f}"
                )
    except (TypeError, ValueError) as exc:
        warnings.append(f"arithmetic_check_error: {exc}")

    return (len(warnings) == 0, warnings)


def _compute_confidence(result: dict, arith_ok: bool) -> float:
    """Heuristic confidence: penalise missing core fields + arithmetic mismatch."""
    score = 1.0
    core = ["vendor_name", "invoice_number", "grand_total", "invoice_date"]
    missing = sum(1 for k in core if not result.get(k))
    score -= 0.12 * missing

    if not arith_ok:
        score -= 0.20

    warnings = result.get("extraction_warnings") or []
    score -= 0.05 * len(warnings)

    return max(0.0, min(1.0, round(score, 3)))


def _infer_currency(text: str) -> str:
    tl = (text or "").lower()
    if " eur" in tl or "€" in tl:
        return "EUR"
    if " gbp" in tl or "£" in tl:
        return "GBP"
    return "USD"


def _parse_amount(raw: str) -> Optional[float]:
    if raw is None:
        return None
    # Remove currency symbols and whitespace, keep separators for locale parsing.
    cleaned = re.sub(r"[£$€¥₹\s]", "", str(raw)).strip()
    # Keep only digits/separators/minus
    cleaned = re.sub(r"[^0-9,.\-]", "", cleaned)
    if not cleaned:
        return None

    # If both comma and dot exist, decide decimal separator by the right-most one.
    # Examples:
    #   21,850.00 -> US style
    #   21.850,00 -> EU style
    if "," in cleaned and "." in cleaned:
        last_comma = cleaned.rfind(",")
        last_dot = cleaned.rfind(".")
        if last_comma > last_dot:
            # EU style
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US style
            cleaned = cleaned.replace(",", "")
    elif re.search(r",\d{2}$", cleaned):
        # Comma appears to be decimal separator.
        cleaned = cleaned.replace(".", "")
        if cleaned.count(",") > 1:
            # Example: 26,220,00 -> 26220.00
            whole, decimals = cleaned.rsplit(",", 1)
            whole = whole.replace(",", "")
            cleaned = f"{whole}.{decimals}"
        else:
            cleaned = cleaned.replace(",", ".")
    else:
        # Default US-style thousands commas.
        cleaned = cleaned.replace(",", "")

    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _normalise_currency(raw: Any, fallback_text: str = "") -> str:
    token = str(raw or "").strip().upper()
    symbol_map = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY", "₹": "INR"}
    if token in symbol_map:
        return symbol_map[token]
    if len(token) == 3 and token.isalpha():
        return token
    return _infer_currency(fallback_text)


def _normalise_extraction_amounts(parsed: dict, source_text: str = "") -> None:
    for field in ("grand_total", "subtotal", "tax_amount"):
        if field in parsed:
            parsed[field] = _parse_amount(parsed.get(field))

    for li in parsed.get("line_items") or []:
        unit = _parse_amount(li.get("unit_price"))
        line_total = _parse_amount(li.get("line_total"))
        if unit is not None:
            li["unit_price"] = unit
        if line_total is not None:
            li["line_total"] = line_total

        qty_raw = li.get("quantity")
        if isinstance(qty_raw, str):
            qty_str = qty_raw.strip()
            # Keep quantity parsing simple and predictable.
            if qty_str.count(",") == 1 and "." not in qty_str:
                qty_str = qty_str.replace(",", ".")
            else:
                qty_str = qty_str.replace(",", "")
            try:
                li["quantity"] = float(qty_str)
            except ValueError:
                pass

    parsed["currency"] = _normalise_currency(parsed.get("currency"), source_text)


def _fallback_extract_from_text(text_content: str, started_at: str, error: str) -> dict:
    """
    Minimal deterministic parser used when Gemini is unavailable (e.g. quota 429).
    Keeps the pipeline usable for demo invoices.
    """
    lines = [ln.strip() for ln in (text_content or "").splitlines() if ln.strip()]
    blob = "\n".join(lines)

    vendor_name = None
    # Common demo format: "Date: YYYY-MM-DD <Vendor Name>"
    m_vendor_on_date = re.search(
        r"(?im)^Date:\s*\d{4}-\d{2}-\d{2}\s+(.+)$",
        blob,
    )
    if m_vendor_on_date:
        vendor_name = m_vendor_on_date.group(1).strip()

    for ln in lines[:12]:
        if vendor_name:
            break
        lnl = ln.lower()
        if any(
            k in lnl
            for k in (
                "invoice",
                "bill to",
                "date",
                "total",
                "due",
                "vat",
                "tax id",
                "remit",
                "bank",
                "iban",
            )
        ):
            continue
        if ":" in ln and len(ln.split(":", 1)[0]) < 20:
            continue
        if re.search(r"(?i)\b(registered|england|wales|company no|vat no)\b", ln):
            continue
        if len(ln) > 2:
            vendor_name = ln[:120]
            break

    invoice_number = None
    m_inv = re.search(
        r"(?i)(?:invoice(?:\s*(?:number|no\.?|#))?\s*[:#]?\s*)([A-Z0-9\-\/]*\d[A-Z0-9\-\/]{1,})",
        blob,
    )
    if m_inv:
        invoice_number = m_inv.group(1).strip()

    po_number = None
    m_po = re.search(r"(?i)(?:po|purchase\s*order)\s*(?:number|no\.?|#)?\s*[:#]?\s*([A-Z0-9\-\/]{2,})", blob)
    if m_po:
        po_number = m_po.group(1).strip()

    line_items: list[dict] = []
    for ln in lines:
        if re.search(r"(?i)^(subtotal|vat|total|description)\b", ln):
            continue
        m_item = re.match(
            r"^\s*(.+?)\s+(\d+(?:[.,]\d+)?)\s+[£$€¥₹]?([\d.,]+)\s+[£$€¥₹]?([\d.,]+)\s*$",
            ln,
        )
        if not m_item:
            continue
        desc = m_item.group(1).strip()
        qty = float(m_item.group(2))
        unit_price = _parse_amount(m_item.group(3))
        line_total = _parse_amount(m_item.group(4))
        if unit_price is None or line_total is None:
            continue
        line_items.append(
            {
                "description": desc,
                "quantity": qty,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    def _find_amount(label_patterns: list[str]) -> Optional[float]:
        for pat in label_patterns:
            m = re.search(pat, blob, flags=re.IGNORECASE)
            if m:
                amt = _parse_amount(m.group(1))
                if amt is not None:
                    return amt
        return None

    subtotal = _find_amount(
        [
            r"subtotal\s*[:\-]?\s*([$€£]?\s*[\d.,]+)",
        ]
    )
    tax_amount = _find_amount(
        [
            r"(?:tax|vat)\s*[:\-]?\s*([$€£]?\s*[\d.,]+)",
        ]
    )
    grand_total = _find_amount(
        [
            r"(?:grand\s*total|total\s*due|amount\s*due)\s*[:\-]?\s*([$€£]?\s*[\d.,]+)",
        ]
    )
    if grand_total is None and subtotal is not None:
        if tax_amount is not None:
            grand_total = round(float(subtotal) + float(tax_amount), 2)
        else:
            grand_total = float(subtotal)

    invoice_date = None
    due_date = None
    m_date = re.search(r"(?i)(?:invoice\s*date|date)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})", blob)
    if m_date:
        invoice_date = m_date.group(1)
    m_due = re.search(r"(?i)(?:due\s*date)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})", blob)
    if m_due:
        due_date = m_due.group(1)

    parsed = {
        "reasoning": (
            "Gemini extraction unavailable; used deterministic text fallback parser. "
            "Extracted core invoice fields from visible text labels."
        ),
        "vendor_name": vendor_name,
        "vendor_address": None,
        "vendor_tax_id": None,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "po_number": po_number,
        "currency": _infer_currency(blob),
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "grand_total": grand_total,
        "line_items": line_items,
        "payment_terms": None,
        "bank_account_change_requested": bool(
            re.search(r"(?i)(bank|iban|routing|account)\s*(change|update|new)", blob)
        ),
        "received_at": started_at,
        "extraction_warnings": [
            "gemini_unavailable_fallback_text_parser",
            f"gemini_error: {error}",
        ],
    }
    arith_ok, arith_warnings = _arithmetic_check(parsed)
    parsed["extraction_warnings"].extend(arith_warnings)
    parsed["extraction_confidence"] = max(0.3, _compute_confidence(parsed, arith_ok))
    parsed["requires_human_review"] = True
    _sanitize_vendor_name(parsed)
    _apply_redaction_guard(parsed)
    _apply_viability_guard(parsed)
    return parsed


def _sanitize_vendor_name(parsed: dict) -> None:
    vendor = parsed.get("vendor_name")
    if not vendor:
        return
    vendor_str = str(vendor).strip()
    looks_like_line_item = bool(
        re.match(
            r"^.+\s+\d+(?:\.\d+)?\s+\$?[\d,]+(?:\.\d{1,2})?\s+\$?[\d,]+(?:\.\d{1,2})?$",
            vendor_str,
        )
    )
    if VAT_PATTERN.match(vendor_str):
        parsed.setdefault("extraction_warnings", []).append(
            f"vendor_name appears to be a tax ID: {vendor_str}"
        )
        parsed["vendor_name"] = None
    elif looks_like_line_item:
        parsed.setdefault("extraction_warnings", []).append(
            f"vendor_name appears to be a line item row: {vendor_str}"
        )
        parsed["vendor_name"] = None


def _apply_redaction_guard(parsed: dict) -> None:
    vendor = parsed.get("vendor_name")
    vendor_norm = str(vendor).strip().lower() if vendor is not None else None
    redacted_norm = {
        str(v).strip().lower() if v is not None else None for v in REDACTED_VENDOR_PATTERNS
    }
    if vendor_norm in redacted_norm:
        parsed.setdefault("extraction_warnings", []).append(
            "vendor_name could not be extracted — may be redacted or unclear"
        )
        parsed["vendor_name"] = None


def check_extraction_viability(extracted: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for field, check in MINIMUM_VIABLE_EXTRACTION.items():
        try:
            if not check(extracted.get(field)):
                failures.append(f"{field} could not be extracted")
        except Exception:  # noqa: BLE001
            failures.append(f"{field} could not be extracted")
    return (len(failures) == 0, failures)


def _apply_viability_guard(parsed: dict) -> None:
    viable, failures = check_extraction_viability(parsed)
    if viable:
        return
    parsed.setdefault("extraction_warnings", []).extend(failures)
    parsed.setdefault("extraction_warnings", []).append(
        "critical_fields_missing_manual_review_required"
    )
    parsed["extraction_confidence"] = min(
        float(parsed.get("extraction_confidence", 1.0) or 1.0), 0.4
    )
    parsed["requires_human_review"] = True


# ── main entry point ──────────────────────────────────────────────────────────
def extract_invoice(file_bytes: bytes, filename: str = "invoice.pdf") -> dict:
    """
    Process a PDF or image. Returns a structured invoice dict including
    extraction_confidence and extraction_warnings.
    """
    started_at = datetime.now(timezone.utc).isoformat()

    is_pdf = file_bytes[:4] == b"%PDF"
    text_content: Optional[str] = None
    fallback_text: Optional[str] = None
    image_bytes: Optional[bytes] = None
    image_mime_type = "image/png"

    if is_pdf:
        text = _try_pdf_text(file_bytes)
        fallback_text = text or None
        if _has_good_text_layer(text):
            text_content = text
            logger.info("doc_intel: using pdfplumber text path (%d chars)", len(text))
        else:
            logger.info("doc_intel: rejecting weak text layer; switching to vision path")
            image_bytes, image_mime_type = _get_image_bytes_and_mime(file_bytes, filename)
            logger.info("doc_intel: falling back to Gemini vision path")
    else:
        image_bytes, image_mime_type = _get_image_bytes_and_mime(file_bytes, filename)

    if not text_content and not image_bytes:
        return {
            "reasoning": "Could not extract text or image from the uploaded file.",
            "vendor_name": None,
            "invoice_number": None,
            "grand_total": None,
            "currency": "USD",
            "line_items": [],
            "extraction_warnings": ["file_unreadable"],
            "extraction_confidence": 0.0,
            "requires_human_review": True,
            "received_at": started_at,
        }

    # Call Gemini
    try:
        model = _get_gemini_model()
        parts = _build_extraction_request(text_content, image_bytes, image_mime_type)
        resp = model.generate_content(parts)
        raw = (getattr(resp, "text", None) or "").strip()
        parsed = _safe_json_loads(raw)
        _normalise_extraction_amounts(parsed, source_text=text_content or fallback_text or "")
    except Exception as exc:  # noqa: BLE001
        logger.error("doc_intel: Gemini call failed: %s", exc)
        if text_content:
            return _fallback_extract_from_text(text_content, started_at, str(exc))
        if fallback_text and len(fallback_text.strip()) >= 20:
            parsed = _fallback_extract_from_text(fallback_text, started_at, str(exc))
            parsed.setdefault("extraction_warnings", []).append(
                "used_low_signal_pdf_text_after_gemini_failure"
            )
            parsed["extraction_confidence"] = min(
                float(parsed.get("extraction_confidence", 0.4) or 0.4), 0.4
            )
            parsed["requires_human_review"] = True
            return parsed
        return {
            "reasoning": f"Extraction failed: {exc}",
            "vendor_name": None,
            "invoice_number": None,
            "grand_total": None,
            "currency": "USD",
            "line_items": [],
            "extraction_warnings": [f"gemini_error: {type(exc).__name__}"],
            "extraction_confidence": 0.0,
            "requires_human_review": True,
            "received_at": started_at,
        }

    # Merge warnings: model's + arithmetic
    arith_ok, arith_warnings = _arithmetic_check(parsed)
    parsed.setdefault("extraction_warnings", [])
    parsed["extraction_warnings"].extend(arith_warnings)
    _sanitize_vendor_name(parsed)
    _apply_redaction_guard(parsed)

    # Stamp arrival time if model didn't supply one
    parsed.setdefault("received_at", started_at)

    # Confidence
    parsed["extraction_confidence"] = _compute_confidence(parsed, arith_ok)
    parsed["requires_human_review"] = (
        parsed["extraction_confidence"] < config.CONFIDENCE_HUMAN_REVIEW_THRESHOLD
    )
    _apply_viability_guard(parsed)

    return parsed


# ── standalone smoke test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    pdf_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(config.DEMO_DIR, "A_clean_software.pdf")
    )
    print(f"\n[doc_intel] Extracting from: {pdf_path}\n")
    out = extract_invoice(pdf_path.read_bytes(), filename=pdf_path.name)
    print(json.dumps(out, indent=2))
