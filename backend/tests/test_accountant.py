"""Unit tests for accountant helper logic (no API calls)."""

from backend.agents.accountant import _build_query, _citation_in_chunks


def test_build_query_includes_vendor_and_items() -> None:
    inv = {
        "vendor_name": "Acme Software",
        "grand_total": 2400,
        "currency": "USD",
        "line_items": [{"description": "Annual subscription"}],
    }
    q = _build_query(inv)
    assert "Acme Software" in q
    assert "Annual subscription" in q
    assert "2400" not in q
    assert "USD" not in q


def test_build_query_skips_fraud_leaking_descriptions() -> None:
    inv = {
        "vendor_name": "X",
        "line_items": [{"description": "Fraud review signal item"}, {"description": "Consulting fee"}],
        "payment_terms": "Net 30",
    }
    q = _build_query(inv)
    assert "Consulting fee" in q
    assert "Fraud" not in q and "fraud" not in q


def test_citation_in_chunks_match() -> None:
    chunks = [
        {"standard": "IFRS 15", "paragraph": "31"},
        {"standard": "IAS 16", "paragraph": "7"},
    ]
    assert _citation_in_chunks("IFRS 15", "Para 31", chunks)
    assert _citation_in_chunks("IAS 16", "Para 7", chunks)


def test_citation_in_chunks_miss() -> None:
    chunks = [{"standard": "IFRS 15", "paragraph": "31"}]
    assert not _citation_in_chunks("ASC 606", "Para 31", chunks)
    assert not _citation_in_chunks("IFRS 15", "Para 99", chunks)


def test_citation_in_chunks_asc720_para() -> None:
    chunks = [{"standard": "ASC 720", "paragraph": "25-1"}]
    assert _citation_in_chunks("ASC 720", "Para 25-1", chunks)
