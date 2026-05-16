"""
SQLAlchemy engine + session factory.

Uses synchronous SQLAlchemy 2.0 style. We fall back gracefully to a local
SQLite file when DATABASE_URL is not reachable so the demo can run without
Postgres if needed (per implementation rule: demo stability > code elegance).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend import config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base shared by db.models and audit.models."""

    pass


def _make_engine() -> Engine:
    """Create SQLAlchemy engine, falling back to SQLite if Postgres fails."""
    url = config.DATABASE_URL
    try:
        eng = create_engine(url, pool_pre_ping=True, future=True)
        # Cheap probe: open + close a connection
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        logger.info("Connected to database: %s", url.split("@")[-1])
        return eng
    except Exception as exc:  # noqa: BLE001
        sqlite_path = os.getenv("SQLITE_FALLBACK", "veridian.db")
        fallback_url = f"sqlite:///{sqlite_path}"
        logger.warning(
            "Postgres unavailable (%s). Falling back to SQLite: %s",
            exc,
            fallback_url,
        )
        return create_engine(
            fallback_url,
            connect_args={"check_same_thread": False},
            future=True,
        )


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone context manager (use outside FastAPI handlers)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all tables defined on Base.metadata if they don't exist."""
    # Import side effect: registers models on Base.metadata
    from backend.audit import models as _audit_models  # noqa: F401
    from backend.db import models as _ops_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured.")
