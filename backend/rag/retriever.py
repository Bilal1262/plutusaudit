"""
HybridRetriever - thin wrapper around VeridianRAG that exposes a clean
API for Agent 2 (Accountant) and Agent 4 (Verifier - citation grounding).

Usage:
    retriever = HybridRetriever()
    retriever.load()                # call once at startup
    chunks = retriever.retrieve("12-month software subscription invoice")

Returns a list of dicts with keys:
    id, standard, paragraph, topic, category, keywords, rule, text, rank,
    dense_score, bm25_score
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import re
import atexit
import threading
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from backend import config

logger = logging.getLogger(__name__)

_EMBED_CACHE_FILE = Path(__file__).resolve().parent / "embed_cache.pkl"
_embed_cache: dict[str, np.ndarray] = {}
_embed_cache_lock = threading.Lock()
_embed_cache_initialized = False


def _load_disk_embed_cache_locked() -> None:
    """Populate _embed_cache from disk when the file exists (call under lock)."""
    global _embed_cache
    if _EMBED_CACHE_FILE.exists():
        try:
            with open(_EMBED_CACHE_FILE, "rb") as f:
                loaded = pickle.load(f)
            if isinstance(loaded, dict):
                _embed_cache = loaded  # expected: md5 hex -> float32 ndarray
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "embed cache: failed to load %s (%s); starting empty",
                _EMBED_CACHE_FILE,
                exc,
            )
            _embed_cache = {}


def _persist_embed_cache_locked() -> None:
    """Write-through cache flush (call under lock)."""
    try:
        with open(_EMBED_CACHE_FILE, "wb") as f:
            pickle.dump(_embed_cache, f)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "embed cache: failed to persist %s (%s)",
            _EMBED_CACHE_FILE,
            exc,
        )


def _persist_embed_cache_at_exit() -> None:
    if not _embed_cache_initialized or not _embed_cache:
        return
    with _embed_cache_lock:
        _persist_embed_cache_locked()


atexit.register(_persist_embed_cache_at_exit)


def get_cached_embedding(text: str, model: object, *, model_id: str) -> np.ndarray:
    """
    Return a query embedding reuse when the same (model_id, text) appears again.
    Persist every 10 cached keys to amortize duplicate HyDE-expanded queries.
    """
    global _embed_cache_initialized

    digest = hashlib.md5(
        f"{model_id}\x00{text}".encode("utf-8"),
    ).hexdigest()

    with _embed_cache_lock:
        if not _embed_cache_initialized:
            _load_disk_embed_cache_locked()
            _embed_cache_initialized = True

        hit = _embed_cache.get(digest)
        if hit is not None:
            return hit

        emb = model.encode(
            [text],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype("float32")
        _embed_cache[digest] = emb

        if len(_embed_cache) % 10 == 0:
            _persist_embed_cache_locked()

        return emb
class HybridRetriever:
    def __init__(self) -> None:
        self.rag = None
        self._loaded = False
        self._fallback_mode = False
        self._fallback_chunks: list[dict] = []

    def load(self) -> "HybridRetriever":
        """
        Load dense/sparse indexes when available.

        If index artifacts are missing (or loading fails), switch to a lightweight
        keyword-overlap fallback so the API can still boot and process invoices.
        """
        index_files = [
            Path(config.RAG_INDEX_PATH),
            Path(config.RAG_CHUNKS_PATH),
            Path(config.RAG_BM25_PATH),
        ]
        if config.ENABLE_FULL_RAG_INDEX and all(p.exists() for p in index_files):
            try:
                from backend.rag.pipeline import VeridianRAG

                self.rag = VeridianRAG()
                self.rag.load()
                self._loaded = True
                self._fallback_mode = False
                return self
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "HybridRetriever: index load failed (%s). Falling back to keyword mode.",
                    exc,
                )
        elif all(p.exists() for p in index_files):
            logger.info(
                "HybridRetriever: FAISS/BM25 artifacts found, but full index loading "
                "is disabled. Set ENABLE_FULL_RAG_INDEX=true to enable dense retrieval."
            )

        self._fallback_chunks = _load_fallback_chunks()
        self._fallback_mode = True
        self._loaded = True
        logger.warning(
            "HybridRetriever running in FALLBACK mode (%d corpus chunks). "
            "Run scripts/build_rag_index.py for FAISS+BM25.",
            len(self._fallback_chunks),
        )
        return self

    def is_loaded(self) -> bool:
        return self._loaded

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 3,
        use_hyde: bool = True,
        gemini_model: Optional[object] = None,
        exclude_categories: Optional[Sequence[str]] = None,
    ) -> list[dict]:
        """
        Run the hybrid retrieval pipeline.

        When use_hyde=True and a Gemini model is supplied, we expand the
        query via HyDE before dense search. BM25 always uses the literal
        query (keyword recall stays strong).

        exclude_categories drops chunks tagged with matching `category`
        metadata (e.g. fraud_control audit rules during GL retrieval).
        """
        if not self._loaded:
            self.load()

        excl = list(exclude_categories or [])

        if self._fallback_mode:
            return _fallback_retrieve(
                self._fallback_chunks,
                query,
                top_k=top_k,
                exclude_categories=excl,
            )

        # We let the VeridianRAG class own the HyDE call so the pipeline
        # remains one cohesive unit and the dense embedding uses the
        # hypothetical document while BM25 uses the literal query.
        if self.rag is None:
            return _fallback_retrieve(
                self._fallback_chunks,
                query,
                top_k=top_k,
                exclude_categories=excl,
            )
        return self.rag.retrieve(
            query,
            gemini_model=gemini_model,
            top_k=top_k,
            use_hyde=use_hyde,
            exclude_categories=excl if excl else None,
        )

    def format_context(self, results: list[dict]) -> str:
        if self._fallback_mode:
            lines = []
            for r in results:
                lines.append(
                    f"[{r.get('standard','Unknown')} Para {r.get('paragraph','?')}] "
                    f"{r.get('topic','')}\n{r.get('rule','')}"
                )
            return "\n\n".join(lines)
        if self.rag is None:
            return ""
        return self.rag.format_context(results)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _load_fallback_chunks() -> list[dict]:
    """
    Parse gaap_ifrs_rules.txt into retrieval chunks, without FAISS/BM25.
    """
    corpus = Path(config.RAG_CORPUS_PATH)
    if not corpus.exists():
        return []
    text = corpus.read_text(encoding="utf-8")
    raw_blocks = [b.strip() for b in text.split("---") if b.strip() and not b.startswith("#")]

    chunks: list[dict] = []
    for i, block in enumerate(raw_blocks):
        meta: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line and line.split(":")[0].isupper():
                key, _, value = line.partition(":")
                meta[key.strip().lower()] = value.strip()
        rule_text = meta.get("rule", "")
        keyword_text = meta.get("keywords", "")
        topic = meta.get("topic", "")
        standard = meta.get("standard", "")
        paragraph = meta.get("paragraph", "")
        category = (meta.get("category") or "").strip()
        doc_text = f"{standard} {paragraph} {topic} {rule_text} {keyword_text}".strip()
        chunks.append(
            {
                "id": f"fallback_{i+1}",
                "standard": standard,
                "paragraph": paragraph,
                "topic": topic,
                "category": category,
                "keywords": keyword_text,
                "rule": rule_text,
                "text": doc_text,
            }
        )
    return chunks


def _fallback_retrieve(
    chunks: list[dict],
    query: str,
    *,
    top_k: int = 3,
    exclude_categories: Optional[Sequence[str]] = None,
) -> list[dict]:
    q = _tokenize(query)
    excl = set(exclude_categories or [])

    def _excluded(c: dict) -> bool:
        if not excl:
            return False
        cat = (c.get("category") or "").strip()
        return cat in excl

    scored: list[tuple[float, dict]] = []
    for c in chunks:
        if _excluded(c):
            continue
        text_tokens = _tokenize(c.get("text", ""))
        if not text_tokens:
            continue
        overlap = len(q & text_tokens)
        # Tiny tie-breaker to prefer chunks with explicit keyword matches.
        kw_tokens = _tokenize(c.get("keywords", ""))
        kw_overlap = len(q & kw_tokens)
        score = float(overlap) + (0.25 * kw_overlap)
        if score > 0:
            scored.append((score, c))

    if not scored:
        # If nothing matches, still return first few chunks to keep flow alive.
        eligible = [c for c in chunks if not _excluded(c)] or chunks
        return [
            {
                **c,
                "rank": i + 1,
                "dense_score": 0.0,
                "bm25_score": 0.0,
            }
            for i, c in enumerate(eligible[:top_k])
        ]

    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for i, (score, c) in enumerate(scored[:top_k]):
        out.append(
            {
                **c,
                "rank": i + 1,
                "dense_score": 0.0,
                "bm25_score": round(score, 3),
            }
        )
    return out


# ── module-level singleton (so all agents share one loaded index) ──────────────
_global_retriever: Optional[HybridRetriever] = None


def get_retriever() -> HybridRetriever:
    """Lazy-init module-level retriever. Loads the index on first call."""
    global _global_retriever
    if _global_retriever is None:
        _global_retriever = HybridRetriever()
        _global_retriever.load()
    return _global_retriever


# ── Smoke test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    r = HybridRetriever()
    r.load()
    queries = [
        "12-month software subscription invoice",
        "Office Depot invoice for Dell laptops",
        "Annual maintenance and support contract",
        "Marketing campaign Google Ads spend",
        "Office cleaning and janitorial services",
    ]
    for q in queries:
        print(f"\nQ: {q}")
        for chunk in r.retrieve(q, use_hyde=False, top_k=2):
            print(
                f"  [{chunk['standard']} Para {chunk['paragraph']}] "
                f"{chunk['topic']}  (dense={chunk['dense_score']:.3f} "
                f"bm25={chunk['bm25_score']:.2f})"
            )
    sys.exit(0)
