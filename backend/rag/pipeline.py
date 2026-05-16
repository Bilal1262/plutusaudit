"""
VeridianAI — RAG Pipeline
Hybrid FAISS (dense) + BM25 (sparse) retrieval with HyDE query expansion
Run this file directly to build the index: python3 rag_pipeline.py
"""

import os, json, math, pickle, hashlib
import numpy as np
import faiss
from pathlib import Path
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from backend.rag.retriever import get_cached_embedding

# ── Config ─────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent  # backend/rag/
CORPUS_FILE   = str(_HERE / "corpus" / "gaap_ifrs_rules.txt")
INDEX_FILE    = str(_HERE / "gaap.faiss")
CHUNKS_FILE   = str(_HERE / "chunks.json")
BM25_FILE     = str(_HERE / "bm25.pkl")
EMBED_MODEL   = "BAAI/bge-small-en-v1.5"
TOP_K_DENSE   = 10
TOP_K_BM25    = 10
TOP_K_FINAL   = 3
RRF_K         = 60          # Reciprocal Rank Fusion constant

# ── Step 1: Parse corpus into chunks ──────────────────────────────────────────
def parse_corpus(filepath: str) -> list[dict]:
    """
    Parse the rules file into structured chunks.
    Each chunk = one accounting rule with metadata.
    """
    text = Path(filepath).read_text()
    raw_chunks = [c.strip() for c in text.split("---") if c.strip()]

    chunks = []
    for raw in raw_chunks:
        if raw.startswith("#"):          # skip comment lines
            continue
        lines = raw.strip().splitlines()
        meta  = {}
        body_lines = []

        for line in lines:
            if ":" in line and line.split(":")[0].isupper():
                key, _, val = line.partition(":")
                meta[key.strip().lower()] = val.strip()
            else:
                body_lines.append(line)

        # Full text = metadata summary + rule body
        full_text = (
            f"Standard: {meta.get('standard','')}, "
            f"Paragraph: {meta.get('paragraph','')}, "
            f"Topic: {meta.get('topic','')}\n"
            f"Rule: {meta.get('rule','')}\n"
            f"Keywords: {meta.get('keywords','')}"
        )

        chunks.append({
            "id":        hashlib.md5(full_text.encode()).hexdigest()[:8],
            "standard":  meta.get("standard", ""),
            "paragraph": meta.get("paragraph", ""),
            "topic":     meta.get("topic", ""),
            "category":  (meta.get("category") or "").strip(),
            "keywords":  meta.get("keywords", ""),
            "rule":      meta.get("rule", ""),
            "text":      full_text,
        })

    print(f"  Parsed {len(chunks)} chunks from corpus")
    return chunks


# ── Step 2: Build FAISS dense index ───────────────────────────────────────────
def build_faiss_index(chunks: list[dict], model: SentenceTransformer):
    texts = [c["text"] for c in chunks]

    print(f"  Embedding {len(texts)} chunks with {EMBED_MODEL}...")
    embeddings = model.encode(
        texts,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True   # cosine similarity via inner product
    ).astype("float32")

    dim   = embeddings.shape[1]
    index = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = 200
    index.hnsw.efSearch        = 64
    index.add(embeddings)

    print(f"  FAISS index built: {index.ntotal} vectors, dim={dim}")
    return index


# ── Step 3: Build BM25 sparse index ───────────────────────────────────────────
def build_bm25_index(chunks: list[dict]) -> BM25Okapi:
    tokenized = [c["text"].lower().split() for c in chunks]
    bm25      = BM25Okapi(tokenized)
    print(f"  BM25 index built over {len(tokenized)} documents")
    return bm25


# ── Step 4: Reciprocal Rank Fusion ────────────────────────────────────────────
def reciprocal_rank_fusion(dense_ids: list, bm25_ids: list,
                            k: int = RRF_K) -> list[int]:
    """
    Merge two ranked lists using RRF.
    score(doc) = sum over lists of 1 / (k + rank)
    Returns doc indices sorted by combined score, highest first.
    """
    scores: dict[int, float] = {}

    for rank, idx in enumerate(dense_ids):
        scores[idx] = scores.get(idx, 0) + 1.0 / (k + rank + 1)

    for rank, idx in enumerate(bm25_ids):
        scores[idx] = scores.get(idx, 0) + 1.0 / (k + rank + 1)

    return sorted(scores.keys(), key=lambda i: scores[i], reverse=True)


# ── Main RAG class ─────────────────────────────────────────────────────────────
class VeridianRAG:
    def __init__(self):
        self.chunks = None
        self.index  = None
        self.bm25   = None
        self.model  = None

    # ── Build (run once) ───────────────────────────────────────────────────────
    def build(self, corpus_file: str = CORPUS_FILE):
        print("\n[RAG] Building index...")

        # Load embedding model
        print(f"  Loading embedding model: {EMBED_MODEL}")
        self.model = SentenceTransformer(EMBED_MODEL)

        # Parse corpus
        self.chunks = parse_corpus(corpus_file)

        # Build indexes
        self.index = build_faiss_index(self.chunks, self.model)
        self.bm25  = build_bm25_index(self.chunks)

        # Save to disk (always under backend/rag/)
        os.makedirs(_HERE, exist_ok=True)
        faiss.write_index(self.index, INDEX_FILE)
        json.dump(self.chunks, open(CHUNKS_FILE, "w"), indent=2)
        pickle.dump(self.bm25,  open(BM25_FILE,  "wb"))

        print(f"\n[RAG] Index saved:")
        print(f"  {INDEX_FILE}")
        print(f"  {CHUNKS_FILE}")
        print(f"  {BM25_FILE}")
        return self

    # ── Load (call this at app startup) ───────────────────────────────────────
    def load(self):
        print("[RAG] Loading index from disk...")
        self.model  = SentenceTransformer(EMBED_MODEL)
        self.index  = faiss.read_index(INDEX_FILE)
        self.chunks = json.load(open(CHUNKS_FILE))
        self.bm25   = pickle.load(open(BM25_FILE, "rb"))
        print(f"[RAG] Loaded {len(self.chunks)} chunks")
        return self

    # ── HyDE: generate hypothetical document ──────────────────────────────────
    def hyde_expand(self, query: str, gemini_model) -> str:
        """
        Hypothetical Document Embeddings:
        Ask Gemini to write a fake IFRS/GAAP paragraph that would answer
        the query, then embed THAT instead of the raw query.
        This dramatically improves retrieval for accounting questions.
        """
        hyde_prompt = (
            f"Write a short (3-5 sentence) IFRS or GAAP accounting rule "
            f"paragraph that directly answers this question:\n\n"
            f"'{query}'\n\n"
            f"Format it as if it were an official standard excerpt. "
            f"Include the journal entry (debit/credit). Be specific."
        )
        try:
            resp = gemini_model.generate_content(hyde_prompt)
            return resp.text.strip()
        except Exception:
            return query   # fallback to original query

    # ── Core retrieval ─────────────────────────────────────────────────────────
    def retrieve(self, query: str,
                 gemini_model=None,
                 top_k: int = TOP_K_FINAL,
                 use_hyde: bool = True,
                 exclude_categories: list | None = None) -> list[dict]:
        """
        Hybrid retrieval:
        1. (Optional) HyDE query expansion via Gemini
        2. Dense FAISS search
        3. Sparse BM25 search
        4. Reciprocal Rank Fusion merge
        5. Return top_k chunks with metadata

        exclude_categories — drop chunks whose `category` is in this list
        (e.g. fraud_control rules for the accountant agent).
        """
        excl = exclude_categories or []
        n_chunks = len(self.chunks)
        dense_k = min(n_chunks, TOP_K_DENSE)
        bm25_k = min(n_chunks, TOP_K_BM25)
        if excl:
            dense_k = min(n_chunks, max(60, top_k * 20))
            bm25_k = min(n_chunks, max(60, top_k * 20))

        # HyDE expansion
        search_query = query
        hyde_doc     = None
        if use_hyde and gemini_model is not None:
            hyde_doc     = self.hyde_expand(query, gemini_model)
            search_query = hyde_doc
            print(f"  [HyDE] Expanded query: {search_query[:80]}...")

        # Dense retrieval (embed HyDE-expanded or literal query; cached per model + text)
        query_emb = get_cached_embedding(search_query, self.model, model_id=EMBED_MODEL)

        scores, dense_ids = self.index.search(query_emb, dense_k)
        dense_ids = dense_ids[0].tolist()

        # Sparse BM25 retrieval (on original query — not HyDE)
        tokenized_query = query.lower().split()
        bm25_scores     = self.bm25.get_scores(tokenized_query)
        bm25_ids        = np.argsort(bm25_scores)[::-1][:bm25_k].tolist()

        # Fuse (wider pool when filtering categories)
        fused_ids = reciprocal_rank_fusion(dense_ids, bm25_ids)

        # Build result
        results = []
        rank = 0
        for idx in fused_ids:
            chunk_src = self.chunks[idx]
            cat = (chunk_src.get("category") or "").strip()
            if excl and cat in excl:
                continue
            rank += 1
            chunk = chunk_src.copy()
            chunk["rank"]         = rank
            chunk["dense_score"]  = float(scores[0][dense_ids.index(idx)])  \
                                    if idx in dense_ids else 0.0
            chunk["bm25_score"]   = float(bm25_scores[idx])
            results.append(chunk)
            if len(results) >= top_k:
                break

        # If filtering removed everything (e.g. stale index), fall back without filter
        if excl and not results and fused_ids:
            for idx in fused_ids[:top_k]:
                rank = len(results) + 1
                chunk = self.chunks[idx].copy()
                chunk["rank"] = rank
                chunk["dense_score"] = float(scores[0][dense_ids.index(idx)]) \
                    if idx in dense_ids else 0.0
                chunk["bm25_score"] = float(bm25_scores[idx])
                results.append(chunk)

        # Top up from BM25 order when many fused hits are excluded
        if len(results) < top_k and excl:
            for ix in np.argsort(bm25_scores)[::-1].tolist():
                if len(results) >= top_k:
                    break
                chunk_src = self.chunks[ix]
                cat = (chunk_src.get("category") or "").strip()
                if cat in excl:
                    continue
                if chunk_src["id"] in {r["id"] for r in results}:
                    continue
                rank = len(results) + 1
                chunk = chunk_src.copy()
                chunk["rank"] = rank
                chunk["dense_score"] = float(scores[0][dense_ids.index(ix)]) \
                    if ix in dense_ids else 0.0
                chunk["bm25_score"] = float(bm25_scores[ix])
                results.append(chunk)

        return results

    # ── Format for prompt injection ───────────────────────────────────────────
    def format_context(self, results: list[dict]) -> str:
        """Format retrieved chunks for injection into the CA agent prompt."""
        lines = []
        for r in results:
            lines.append(
                f"[{r['standard']} Para {r['paragraph']}] "
                f"{r['topic']}\n{r['rule']}"
            )
        return "\n\n".join(lines)


# ── Smoke test ─────────────────────────────────────────────────────────────────
def smoke_test(rag: VeridianRAG):
    test_queries = [
        "How should a 12-month software subscription invoice be classified?",
        "We received an invoice for 2 Dell laptops costing $850 each",
        "Invoice for office cleaning and janitorial services",
        "Annual insurance premium invoice for $12,000",
        "Consulting services invoice from a strategy firm $45,000",
        "Invoice for printing marketing brochures",
    ]

    print("\n" + "="*60)
    print("SMOKE TEST — Retrieval without HyDE")
    print("="*60)

    for query in test_queries:
        results = rag.retrieve(query, gemini_model=None, use_hyde=False)
        top     = results[0]
        print(f"\nQ: {query}")
        print(f"   → [{top['standard']} Para {top['paragraph']}] {top['topic']}")
        print(f"      BM25={top['bm25_score']:.2f}  Dense={top['dense_score']:.3f}")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    rag = VeridianRAG()

    if "--load" in sys.argv:
        # Load existing index and run smoke test
        rag.load()
    else:
        # Build fresh index
        rag.build()

    smoke_test(rag)
    print("\n[RAG] Pipeline ready. Import VeridianRAG in your agents.")
