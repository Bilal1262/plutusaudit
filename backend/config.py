"""
VeridianAI - Central configuration.

All env-driven values and tunable thresholds live here.
Never hardcode secrets; always read from environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

PROMPTS_DIR = BACKEND_DIR / "prompts"
RAG_DIR = BACKEND_DIR / "rag"
DATA_DIR = PROJECT_ROOT / "data"

RAG_INDEX_PATH = str(RAG_DIR / "gaap.faiss")
RAG_CHUNKS_PATH = str(RAG_DIR / "chunks.json")
RAG_BM25_PATH = str(RAG_DIR / "bm25.pkl")
RAG_CORPUS_PATH = str(RAG_DIR / "corpus" / "gaap_ifrs_rules.txt")
ENABLE_FULL_RAG_INDEX = os.getenv("ENABLE_FULL_RAG_INDEX", "false").lower() in {
    "1",
    "true",
    "yes",
}

VENDOR_HISTORY_PATH = str(DATA_DIR / "vendor_history.json")
DEMO_DIR = str(DATA_DIR / "demo")


# ── API Keys ───────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
FEATHERLESS_API_KEY = os.getenv("FEATHERLESS_API_KEY", "")
FEATHERLESS_BASE_URL = os.getenv(
    "FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:password@localhost:5432/veridian",
)
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


# ── Model names ────────────────────────────────────────────────────────────────
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
FEATHERLESS_MODEL = os.getenv("FEATHERLESS_MODEL", "Qwen/Qwen3-32B")
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"

AGENT_VERSION = "1.0.0"


# ── Confidence / fraud thresholds ──────────────────────────────────────────────
CONFIDENCE_HUMAN_REVIEW_THRESHOLD = 0.70
FRAUD_REVIEW_THRESHOLD = 30
FRAUD_BLOCK_THRESHOLD = 70

BENFORD_MAD_THRESHOLD = 0.015
APPROVAL_THRESHOLDS = [1000, 5000, 10000, 25000, 50000]
BELOW_THRESHOLD_MARGIN = 0.05

VERIFIER_MAX_RETRIES = 2

# Vague description heuristic words (fraud signal)
VAGUE_WORDS = {
    "services",
    "consulting",
    "miscellaneous",
    "other",
    "fee",
    "fees",
    "work",
    "services rendered",
    "professional",
}


# ── Chart of accounts (used by Verifier 3 — schema conformance) ────────────────
CHART_OF_ACCOUNTS = [
    "Accounts Payable",
    "Prepaid Expenses",
    "Prepaid Maintenance",
    "Prepaid Consulting",
    "Prepaid Insurance",
    "Office Supplies Expense",
    "Unclassified Expense - Review",
    "Unclassified Expense - Manual Review",
    "Suspense Account",
    "Computer Equipment",
    "Furniture and Fittings",
    "Fixed Assets",
    "IT Equipment Expense",
    "Professional Services Expense",
    "Rent Expense",
    "Marketing Expense",
    "Advertising Expense",
    "Travel Expense",
    "R&D Expense",
    "Utilities Expense",
    "Training Expense",
    "Intangible Assets - Software",
    "Maintenance Expense",
    "Inventory",
    "Subscription Expense",
    "Right-of-Use Asset",
    "Lease Liability",
    "Insurance Expense",
]


def reload_keys_from_env() -> None:
    """Helper so tests / runtime reloads can pull new env values."""
    global GEMINI_API_KEY, FEATHERLESS_API_KEY, DATABASE_URL, ENVIRONMENT
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY)
    FEATHERLESS_API_KEY = os.getenv("FEATHERLESS_API_KEY", FEATHERLESS_API_KEY)
    DATABASE_URL = os.getenv("DATABASE_URL", DATABASE_URL)
    ENVIRONMENT = os.getenv("ENVIRONMENT", ENVIRONMENT)
