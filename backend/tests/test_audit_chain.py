"""
End-to-end test of the hash-chained audit log.

Uses an in-memory SQLite engine so the test runs without Postgres.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.audit.chain import append_entry, hash_input, verify_chain
from backend.audit.models import AuditEntry
from backend.db.session import Base


def _make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    # Make sure the audit table model is registered on Base.metadata
    import backend.audit.models  # noqa: F401
    import backend.db.models  # noqa: F401

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_append_entries_produces_valid_chain() -> None:
    db = _make_session()

    for i in range(5):
        append_entry(
            db,
            agent_name=f"agent_{i}",
            model_name="test-model",
            input_data={"i": i},
            output_data={"out": i * 2},
            confidence=0.9,
            reasoning=f"step {i}",
        )

    result = verify_chain(db)
    assert result["valid"] is True
    assert result["count"] == 5


def test_chain_links_prev_hash_correctly() -> None:
    db = _make_session()
    e1 = append_entry(db, agent_name="a", model_name="m", input_data={}, output_data={})
    e2 = append_entry(db, agent_name="b", model_name="m", input_data={}, output_data={})
    assert e2.prev_hash == e1.entry_hash


def test_tamper_detected_when_output_changed() -> None:
    db = _make_session()
    for i in range(3):
        append_entry(
            db,
            agent_name=f"a{i}",
            model_name="m",
            input_data={"i": i},
            output_data={"v": i},
        )

    # Tamper: mutate the middle row's output directly
    row = db.query(AuditEntry).filter_by(sequence=2).first()
    row.output = dict(row.output or {})
    row.output["_tampered"] = True
    db.commit()

    result = verify_chain(db)
    assert result["valid"] is False
    assert result["broken_at_sequence"] == 2


def test_hash_input_is_deterministic() -> None:
    a = hash_input({"x": 1, "y": [1, 2, 3]})
    b = hash_input({"y": [1, 2, 3], "x": 1})
    assert a == b


def test_empty_chain_is_valid() -> None:
    db = _make_session()
    result = verify_chain(db)
    assert result == {"valid": True, "count": 0}
