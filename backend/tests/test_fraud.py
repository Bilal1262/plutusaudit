"""Unit tests for deterministic fraud signals (no API calls)."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from backend.agents.fraud import (
    _apply_signal_floor,
    _benford_mad,
    _heuristic_score,
    _is_below_threshold,
    _is_round_number,
    _levenshtein,
    _off_hours,
    _vague_description,
    compute_signals,
)


def test_round_number() -> None:
    assert _is_round_number(5000)
    assert _is_round_number(1500)
    assert not _is_round_number(4950)
    assert not _is_round_number(0)


def test_below_threshold() -> None:
    # $4950 lies within 5% below $5,000
    assert _is_below_threshold(4950)
    # $4500 is well below; outside the 5% margin (4750 is the cutoff)
    assert not _is_below_threshold(4500)
    # exactly threshold should not fire
    assert not _is_below_threshold(5000)


def test_levenshtein_basic() -> None:
    assert _levenshtein("INV-001", "INV-001") == 0
    assert _levenshtein("INV-001", "INV-002") == 1
    assert _levenshtein("abc", "xyz") == 3


def test_vague_description_fires() -> None:
    assert _vague_description([{"description": "Services"}])
    assert _vague_description([{"description": "consulting"}])
    assert not _vague_description(
        [{"description": "Acme Cloud annual subscription"}]
    )


def test_off_hours() -> None:
    ts = datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc).isoformat()
    assert _off_hours(ts)
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    assert not _off_hours(ts)


def test_benford_returns_none_for_small_history() -> None:
    assert _benford_mad([1, 2, 3]) is None


def test_benford_known_distribution() -> None:
    # A Benford-compliant distribution should give a low MAD.
    amounts = []
    for d in range(1, 10):
        count = int(1000 * math.log10(1 + 1 / d))
        amounts.extend([d * 10 + 0.5] * count)
    mad = _benford_mad(amounts)
    assert mad is not None and mad < 0.01


def test_heuristic_score_clean() -> None:
    signals = {
        "exact_duplicate": False,
        "near_duplicate_count": 0,
        "benford_flag": False,
        "round_number": False,
        "below_threshold": False,
        "missing_po": False,
        "vague_description": False,
        "new_vendor": False,
        "off_hours_submission": False,
        "bank_account_change_requested": False,
    }
    r = _heuristic_score(signals)
    assert r["tier"] == "clean"
    assert r["risk_score"] < 30


def test_heuristic_score_shell_company_pattern() -> None:
    signals = {
        "exact_duplicate": False,
        "near_duplicate_count": 0,
        "benford_flag": False,
        "round_number": False,
        "below_threshold": True,
        "missing_po": True,
        "vague_description": True,
        "new_vendor": True,
        "off_hours_submission": False,
        "bank_account_change_requested": False,
    }
    r = _heuristic_score(signals)
    assert r["risk_score"] > 60
    assert r["tier"] in ("block", "review")


def test_heuristic_exact_duplicate_alone_blocks() -> None:
    signals = {
        "exact_duplicate": True,
        "near_duplicate_count": 0,
        "benford_flag": False,
        "round_number": False,
        "below_threshold": False,
        "missing_po": False,
        "vague_description": False,
        "new_vendor": False,
        "off_hours_submission": False,
        "bank_account_change_requested": False,
    }

    result = _heuristic_score(signals)

    assert result["risk_score"] == 70
    assert result["tier"] == "block"
    assert result["recommended_action"] == "block and escalate to controller"


def test_exact_duplicate_forces_block_floor() -> None:
    signals = {
        "exact_duplicate": True,
        "near_duplicate_count": 0,
        "benford_flag": False,
        "round_number": False,
        "below_threshold": False,
        "missing_po": False,
        "vague_description": False,
        "new_vendor": False,
        "off_hours_submission": False,
        "bank_account_change_requested": False,
    }
    llm_result = {
        "risk_score": 30,
        "tier": "review",
        "top_3_signals": [],
        "recommended_action": "route to AP manager",
    }

    result = _apply_signal_floor(llm_result, signals)

    assert result["risk_score"] == 70
    assert result["tier"] == "block"
    assert result["recommended_action"] == "block and escalate to controller"
    assert "exact_duplicate_floor_applied" in result["guard_warnings"]


def test_exact_duplicate_with_missing_po_forces_stronger_block_floor() -> None:
    signals = {
        "exact_duplicate": True,
        "near_duplicate_count": 0,
        "benford_flag": False,
        "round_number": False,
        "below_threshold": False,
        "missing_po": True,
        "vague_description": True,
        "new_vendor": False,
        "off_hours_submission": False,
        "bank_account_change_requested": False,
    }
    llm_result = {
        "risk_score": 30,
        "tier": "review",
        "top_3_signals": [],
        "recommended_action": "route to AP manager",
    }

    result = _apply_signal_floor(llm_result, signals)

    assert result["risk_score"] == 85
    assert result["tier"] == "block"
    assert result["recommended_action"] == "block and escalate to controller"
    assert "exact_duplicate_missing_po_floor_applied" in result["guard_warnings"]


def test_near_duplicate_with_missing_po_forces_review_floor() -> None:
    signals = {
        "exact_duplicate": False,
        "near_duplicate_count": 1,
        "benford_flag": False,
        "round_number": False,
        "below_threshold": False,
        "missing_po": True,
        "vague_description": False,
        "new_vendor": False,
        "off_hours_submission": False,
        "bank_account_change_requested": False,
    }
    llm_result = {
        "risk_score": 20,
        "tier": "clean",
        "top_3_signals": [],
        "recommended_action": "auto-pay",
    }

    result = _apply_signal_floor(llm_result, signals)

    assert result["risk_score"] == 50
    assert result["tier"] == "review"
    assert result["recommended_action"] == "route to AP manager"
    assert "near_duplicate_missing_po_floor_applied" in result["guard_warnings"]
