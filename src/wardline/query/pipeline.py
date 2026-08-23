"""The query plane's `answer()` orchestration — mirrors the report's 5.10
pseudocode: understand -> plan -> parallel retrieve -> fuse+rerank -> graph
expansion -> context assembly -> grounded synthesis -> citation
verification -> audit close.

Phase 4 implements the text-only path; graph_lookup (Phase 5) is wired in as
a no-op until the knowledge graph plane exists, so `mode="auto"` degrades
gracefully to text-only until then.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from wardline.common.logging import get_logger
from wardline.governance import audit, pep
from wardline.query import planner, understanding
from wardline.query.llm_client import get_llm_client
from wardline.query.render import watermark
from wardline.query.verify import verify_citations
from wardline.retrieval.embeddings import embed_query
from wardline.retrieval.fusion import FusedResult, rrf_merge
from wardline.retrieval.lexical import lexical_search
from wardline.retrieval.rerank import rerank
from wardline.retrieval.vector import vector_search
from wardline.storage.models.governance import User

logger = get_logger(__name__)


def _merge_filters(question: str, filters: dict) -> dict:
    merged = dict(filters)
    for key, value in understanding.extract_constraints(question).items():
        merged.setdefault(key, value)
    if isinstance(merged.get("published_after"), str):
        merged["published_after"] = datetime.fromisoformat(merged["published_after"])
    return merged


def _graph_lookup(question: str) -> list[FusedResult]:
    """Phase 5 fills this in with real Neo4j traversal; empty until then."""
    try:
        from wardline.graph.query_support import graph_lookup_for_question

        return graph_lookup_for_question(question)
    except ImportError:
        return []


def _fetch_source_metadata(db: Session, chunk_ids: list[str]) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT c.id, c.doc_id, d.uri, d.title, d.license
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE c.id = ANY(:ids)
            """
        ),
        {"ids": chunk_ids},
    ).fetchall()
    return {r[0]: {"doc_id": r[1], "uri": r[2], "title": r[3], "license": r[4]} for r in rows}


def answer(
    db: Session,
    *,
    user: User,
    question: str,
    mode: str = "auto",
    filters: dict | None = None,
    max_sources: int = 12,
) -> dict:
    filters = filters or {}
    start = time.monotonic()
    user_id = user.id

    session_id = audit.open_session(db, user_id, question, mode)

    llm = get_llm_client()
    subquestions = planner.plan(llm, question)
    merged_filters = _merge_filters(question, filters)

    ranked_lists: list = []
    graph_candidates: list[FusedResult] = []
    for sq in subquestions:
        if sq.route in ("text", "both"):
            lex = lexical_search(db, sq.q, filters=merged_filters)
            vec = vector_search(db, embed_query(sq.q), filters=merged_filters)
            ranked_lists.extend([lex, vec])
        if sq.route in ("graph", "both") and mode in ("auto", "research"):
            graph_candidates.extend(_graph_lookup(sq.q))

    fused = rrf_merge(*ranked_lists) if ranked_lists else []
    # graph facts are folded in alongside text candidates before reranking, so
    # the reranker can weigh a precise graph fact against paraphrased prose.
    combined = _dedupe(fused + graph_candidates)
    ranked = rerank(question, combined, top_n=max_sources)

    chunk_ids = [r.chunk_id for r in ranked if not r.chunk_id.startswith("edge_")]
    metadata = _fetch_source_metadata(db, chunk_ids)

    sources_payload = []
    for r in ranked:
        meta = metadata.get(r.chunk_id, {})
        kind = "edge" if r.chunk_id.startswith("edge_") else "chunk"
        sources_payload.append(
            {
                "id": r.chunk_id,
                "text": r.text,
                "label": kind,
                "doc_id": meta.get("doc_id"),
                "uri": meta.get("uri"),
                "title": meta.get("title"),
                "license": meta.get("license"),
                "kind": kind,
            }
        )

    # ABAC, enforced right before the evidence is handed to the LLM (report
    # 4.6): a viewer never sees internal-only sources, even ones retrieval
    # itself surfaced.
    sources_payload = pep.filter_sources_by_license(user, sources_payload)

    raw_answer = llm.synthesize(question, sources_payload)
    valid_ids = {s["id"] for s in sources_payload}
    verified = verify_citations(raw_answer, valid_ids)

    final_text = watermark(session_id, verified.text) if verified.text else ""
    latency_ms = int((time.monotonic() - start) * 1000)
    answer_hash = hashlib.sha256(final_text.encode("utf-8")).hexdigest()

    cited_source_ids = sorted({sid for claim in verified.claims for sid in claim.supported_by})
    used_sources = [s for s in sources_payload if s["id"] in cited_source_ids]

    audit.close_session(
        db,
        session_id,
        user_id,
        retrieved=[s["id"] for s in sources_payload],
        latency_ms=latency_ms,
        answer_hash=answer_hash,
    )

    return {
        "session_id": session_id,
        "answer": final_text
        if not verified.insufficient_evidence
        else "The available sources do not answer this question.",
        "claims": [{"id": c.id, "text": c.text, "supported_by": c.supported_by} for c in verified.claims],
        "sources": [
            {
                "id": s["id"],
                "doc_id": s.get("doc_id"),
                "uri": s.get("uri"),
                "title": s.get("title"),
                "license": s.get("license"),
                "kind": s["kind"],
            }
            for s in used_sources
        ],
        "confidence": verified.confidence,
        "insufficient_evidence": verified.insufficient_evidence,
        "latency_ms": latency_ms,
    }


def _dedupe(candidates: list[FusedResult]) -> list[FusedResult]:
    seen: dict[str, FusedResult] = {}
    for c in candidates:
        if c.chunk_id not in seen or c.rrf_score > seen[c.chunk_id].rrf_score:
            seen[c.chunk_id] = c
    return sorted(seen.values(), key=lambda r: r.rrf_score, reverse=True)
