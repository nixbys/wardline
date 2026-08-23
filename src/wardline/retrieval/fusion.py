"""Reciprocal Rank Fusion (report 5.5): merges ranked lists without needing
comparable scores. `score(d) = sum over lists of 1 / (k + rank_i(d))`.
"""

from __future__ import annotations

from dataclasses import dataclass

from wardline.common.config import get_settings
from wardline.retrieval.lexical import RetrievedChunk


@dataclass
class FusedResult:
    chunk_id: str
    doc_id: str
    text: str
    rrf_score: float


def rrf_merge(*ranked_lists: list[RetrievedChunk], k: int | None = None) -> list[FusedResult]:
    k = k or get_settings().rrf_k
    scores: dict[str, float] = {}
    meta: dict[str, RetrievedChunk] = {}

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (k + rank)
            meta.setdefault(item.chunk_id, item)

    fused = [
        FusedResult(chunk_id=cid, doc_id=meta[cid].doc_id, text=meta[cid].text, rrf_score=score)
        for cid, score in scores.items()
    ]
    fused.sort(key=lambda r: r.rrf_score, reverse=True)
    return fused
