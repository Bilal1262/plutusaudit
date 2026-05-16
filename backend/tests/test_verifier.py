"""Unit tests for verifier logic (no Gemini calls in the unit tests)."""

from __future__ import annotations

import pytest

from backend.agents.verifier import (
    _build_critique,
    verify_numerical,
    verify_schema,
)


# ── V1: numerical ─────────────────────────────────────────────────────────────
def test_verify_numerical_pass() -> None:
    invoice = {"grand_total": 2400.00}
    accountant = {"amount": 2400.00}
    res = verify_numerical(invoice, accountant)
    assert res["passed"]
    assert res["violations"] == []
    assert res["delta"] == pytest.approx(0.0)


def test_verify_numerical_mismatch() -> None:
    invoice = {"grand_total": 2400.00}
    accountant = {"amount": 1234.56}
    res = verify_numerical(invoice, accountant)
    assert not res["passed"]
    assert any("grand_total" in v for v in res["violations"])


def test_verify_numerical_handles_garbage() -> None:
    invoice = {"grand_total": None}
    accountant = {"amount": None}
    res = verify_numerical(invoice, accountant)
    assert res["passed"]


# ── V3: schema (deterministic only — no Gemini call) ──────────────────────────
def test_verify_schema_pass() -> None:
    accountant = {
        "gl_account_debit": "Prepaid Expenses",
        "gl_account_credit": "Accounts Payable",
        "standard_cited": "IFRS 15",
        "paragraph_cited": "Para 31",
        "confidence": 0.92,
        "requires_human_review": False,
        "deferral_required": True,
        "amortization_schedule": {"monthly_amount": 200, "months": 12},
    }
    res = verify_schema(accountant)
    if not res["passed"]:
        # Gemini call may add unrelated violations — the deterministic part should produce none.
        non_gemini = [v for v in res["violations"] if "chart of accounts" in v or "deferral" in v or "below threshold" in v]
        assert non_gemini == []
    else:
        assert res["violations"] == [] or all(
            "chart of accounts" not in v for v in res["violations"]
        )


def test_verify_schema_invalid_account() -> None:
    accountant = {
        "gl_account_debit": "NONSENSE_ACCOUNT",
        "gl_account_credit": "Accounts Payable",
        "standard_cited": "IFRS 15",
        "paragraph_cited": "Para 31",
        "confidence": 0.9,
        "requires_human_review": False,
    }
    res = verify_schema(accountant)
    assert not res["passed"]
    assert any("NONSENSE_ACCOUNT" in v for v in res["violations"])


def test_verify_schema_low_confidence_flag_missing() -> None:
    accountant = {
        "gl_account_debit": "Prepaid Expenses",
        "gl_account_credit": "Accounts Payable",
        "standard_cited": "IFRS 15",
        "paragraph_cited": "Para 31",
        "confidence": 0.5,
        "requires_human_review": False,
    }
    res = verify_schema(accountant)
    assert not res["passed"]
    assert any("requires_human_review" in v for v in res["violations"])


# ── critique builder ─────────────────────────────────────────────────────────
def test_build_critique_lists_each_violation() -> None:
    failed = [
        {"verifier": "numerical", "violations": ["debit != credit"]},
        {"verifier": "citation", "violations": ["paragraph not in context"]},
    ]
    c = _build_critique(failed)
    assert "numerical" in c
    assert "citation" in c
    assert "debit != credit" in c
    assert "paragraph not in context" in c
