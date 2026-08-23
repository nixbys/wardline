"""Agent tool implementations (report 5.8): the actual dispatch functions
the loop calls once the LLM has decided which tool+args to use. Every tool
returns a uniform `list[dict]` shape with an "id" and "text" so the loop can
gather citations generically regardless of which tool produced them.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.graph.entity_resolution.scoring import score_pair
from wardline.retrieval.embeddings import embed_query
from wardline.retrieval.fusion import rrf_merge
from wardline.retrieval.lexical import lexical_search
from wardline.retrieval.vector import vector_search
from wardline.storage.models.entities import Entity

RESOLVE_ENTITY_THRESHOLD = 0.6


def search_text(db: Session, query: str, k: int = 10, filters: dict | None = None) -> list[dict]:
    lex = lexical_search(db, query, k=k, filters=filters or {})
    vec = vector_search(db, embed_query(query), k=k, filters=filters or {})
    fused = rrf_merge(lex, vec)
    return [{"id": r.chunk_id, "text": r.text} for r in fused[:k]]


def graph_lookup(db: Session, entity: str, relation: str | None = None, hops: int = 1) -> list[dict]:
    from wardline.graph.query_support import graph_lookup_for_question

    results = graph_lookup_for_question(entity, hops=hops)
    if relation:
        results = [r for r in results if relation.lower() in r.text.lower()]
    return [{"id": r.chunk_id, "text": r.text} for r in results]


def resolve_entity(db: Session, name: str, context: str = "") -> list[dict]:
    candidates = list(db.execute(select(Entity)).scalars())
    best, best_score = None, 0.0
    for candidate in candidates:
        score = score_pair(name, candidate.canonical_name)
        if score > best_score:
            best_score, best = score, candidate
    if best is None or best_score < RESOLVE_ENTITY_THRESHOLD:
        return []
    return [{"id": best.id, "text": f"Resolved '{name}' to entity '{best.canonical_name}' ({best.type})"}]
