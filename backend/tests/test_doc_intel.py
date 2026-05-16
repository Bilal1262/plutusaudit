"""Smoke test for doc_intel - no Gemini call required."""

from backend.agents.doc_intel import _arithmetic_check, _compute_confidence


def test_arithmetic_check_pass() -> None:
    result = {
        "subtotal": 100.0,
        "tax_amount": 10.0,
        "grand_total": 110.0,
        "line_items": [
            {"line_total": 60.0},
            {"line_total": 40.0},
        ],
    }
    ok, warnings = _arithmetic_check(result)
    assert ok
    assert warnings == []


def test_arithmetic_check_fail() -> None:
    result = {
        "subtotal": 100.0,
        "tax_amount": 10.0,
        "grand_total": 999.0,
        "line_items": [{"line_total": 60.0}, {"line_total": 40.0}],
    }
    ok, warnings = _arithmetic_check(result)
    assert not ok
    assert any("grand_total" in w for w in warnings)


def test_confidence_drops_with_missing_fields() -> None:
    full = {
        "vendor_name": "x",
        "invoice_number": "y",
        "grand_total": 1,
        "invoice_date": "2024-01-01",
        "extraction_warnings": [],
    }
    empty = {"extraction_warnings": []}
    assert _compute_confidence(full, True) > _compute_confidence(empty, True)
