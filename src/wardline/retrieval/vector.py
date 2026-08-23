"""Semantic (vector) retrieval (report 4.4/5.5): pgvector ANN search (HNSW)
over chunk embeddings, cosine distance.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.retrieval.lexical import RetrievedChunk

_QUERY = """
SELECT c.id, c.doc_id, c.text, 1 - (c.embedding <=> (:embedding)::vector) AS score
FROM chunks c
JOIN documents d ON d.id = c.doc_id
WHERE c.embedding IS NOT NULL
  AND d.status = 'active'
  AND (CAST(:lang AS text) IS NULL OR d.lang = CAST(:lang AS text))
  AND (
    CAST(:published_after AS timestamptz) IS NULL
    OR d.published_at >= CAST(:published_after AS timestamptz)
  )
ORDER BY c.embedding <=> (:embedding)::vector
LIMIT :k
"""


def vector_search(
    db: Session, embedding: list[float], k: int | None = None, filters: dict | None = None
) -> list[RetrievedChunk]:
    filters = filters or {}
    k = k or get_settings().vector_top_k
    rows = db.execute(
        text(_QUERY),
        {
            "embedding": str(embedding),
            "lang": filters.get("lang"),
            "published_after": filters.get("published_after"),
            "k": k,
        },
    ).fetchall()
    return [RetrievedChunk(chunk_id=r[0], doc_id=r[1], text=r[2], score=float(r[3])) for r in rows]
