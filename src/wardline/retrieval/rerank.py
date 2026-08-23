"""Cross-encoder reranking (report 5.5): scores each surviving passage
jointly with the query for precise relevance. Local model, CPU, no paid API.
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import CrossEncoder

from wardline.common.config import get_settings
from wardline.retrieval.fusion import FusedResult


@lru_cache
def _model() -> CrossEncoder:
    return CrossEncoder(get_settings().reranker_model)


def rerank(query: str, candidates: list[FusedResult], top_n: int | None = None) -> list[FusedResult]:
    if not candidates:
        return []
    top_n = top_n or get_settings().rerank_top_n
    pairs = [(query, c.text) for c in candidates]
    scores = _model().predict(pairs)
    ordered = [
        c for _, c in sorted(zip(scores, candidates, strict=True), key=lambda x: x[0], reverse=True)
    ]
    return ordered[:top_n]
