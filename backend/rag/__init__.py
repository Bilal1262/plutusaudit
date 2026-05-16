"""RAG package - HyDE-expanded hybrid FAISS+BM25 retrieval."""

__all__ = ["VeridianRAG", "HybridRetriever"]


def __getattr__(name: str):
    if name == "VeridianRAG":
        from .pipeline import VeridianRAG

        return VeridianRAG
    if name == "HybridRetriever":
        from .retriever import HybridRetriever

        return HybridRetriever
    raise AttributeError(name)
