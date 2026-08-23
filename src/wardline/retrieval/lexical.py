"""Lexical (keyword) retrieval (report 4.4/5.5): Postgres tsvector + GIN,
ranked with `ts_rank_cd`. This is a BM25-*like* approximation, not true BM25
(documented gap; ParadeDB's `pg_search` is the noted upgrade path if ranking
fidelity needs to improve without leaving Postgres).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from wardline.common.config import get_settings


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    text: str
    score: float


_QUERY = """
SELECT c.id, c.doc_id, c.text, ts_rank_cd(c.tsv, websearch_to_tsquery('pg_catalog.english', :q)) AS score
FROM chunks c
JOIN documents d ON d.id = c.doc_id
WHERE c.tsv @@ websearch_to_tsquery('pg_catalog.english', :q)
  AND d.status = 'active'
  AND (CAST(:lang AS text) IS NULL OR d.lang = CAST(:lang AS text))
  AND (
    CAST(:published_after AS timestamptz) IS NULL
    OR d.published_at >= CAST(:published_after AS timestamptz)
  )
ORDER BY score DESC
LIMIT :k
"""


def lexical_search(
    db: Session, query: str, k: int | None = None, filters: dict | None = None
) -> list[RetrievedChunk]:
    if get_settings().lexical_backend == "opensearch":
        from wardline.retrieval.opensearch_backend import lexical_search_opensearch

        return lexical_search_opensearch(query, k, filters)

    filters = filters or {}
    k = k or get_settings().lexical_top_k
    rows = db.execute(
        text(_QUERY),
        {
            "q": query,
            "lang": filters.get("lang"),
            "published_after": filters.get("published_after"),
            "k": k,
        },
    ).fetchall()
    return [RetrievedChunk(chunk_id=r[0], doc_id=r[1], text=r[2], score=float(r[3])) for r in rows]
