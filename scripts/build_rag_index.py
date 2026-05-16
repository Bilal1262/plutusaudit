"""
Build the FAISS + BM25 + chunks index.

Run once before starting the API server:
    python -m scripts.build_rag_index
"""


from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.pipeline import VeridianRAG, smoke_test  # noqa: E402


#the purpose is to build the RAG whenever we add some new data

def main() -> None:
    rag = VeridianRAG()
    rag.build()
    print("\n[build_rag_index] Index built. Running smoke test...")
    smoke_test(rag)


if __name__ == "__main__":
    main()
