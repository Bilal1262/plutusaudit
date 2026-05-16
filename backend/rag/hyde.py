"""
HyDE - Hypothetical Document Embeddings.

Generates a synthetic IFRS/GAAP paragraph that *would* answer the query,
then embeds that synthetic doc instead of the literal user query. This is
the FinSage-grade move (arXiv:2504.14493): synthetic docs sit in the same
vector neighbourhood as real standards, dramatically improving recall on
accounting questions.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


HYDE_PROMPT_TEMPLATE = (
    "Write a short (3-5 sentence) IFRS or GAAP accounting rule paragraph "
    "that directly answers this question:\n\n"
    "'{query}'\n\n"
    "Format it as if it were an official standard excerpt. Include the "
    "journal entry (debit/credit). Be specific. DO NOT speculate beyond "
    "established accounting standards."
)


def hyde_expand(query: str, gemini_model: Optional[object] = None) -> str:
    """
    Generate a HyDE-expanded query.

    `gemini_model` is a `google.generativeai.GenerativeModel` instance with
    a `.generate_content(prompt)` method. If it's None, we fall back to the
    original query (graceful degradation, never break the pipeline).
    """
    if gemini_model is None:
        return query

    prompt = HYDE_PROMPT_TEMPLATE.format(query=query)

    try:
        resp = gemini_model.generate_content(prompt)
        text = (getattr(resp, "text", None) or "").strip()
        return text if text else query
    except Exception as exc:  # noqa: BLE001
        logger.warning("HyDE expansion failed: %s. Falling back to raw query.", exc)
        return query
