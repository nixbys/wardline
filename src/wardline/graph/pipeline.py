"""Knowledge & fusion plane orchestration (report 4.5): for each newly
indexed document, extract mentions and relation candidates, resolve
mentions against the existing entity graph (blocking -> scoring ->
clustering, with low-confidence merges routed to human review instead of
auto-merged), promote resolved candidates into canonical entities/edges,
and mirror them into Neo4j.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.common.logging import get_logger
from wardline.graph import sync
from wardline.graph.entity_resolution.blocking import block_key
from wardline.graph.entity_resolution.review import (
    HIGH_CONFIDENCE_THRESHOLD,
    REVIEW_THRESHOLD,
    queue_for_review,
)
from wardline.graph.entity_resolution.scoring import score_pair
from wardline.graph.ner import Mention, extract_mentions
from wardline.graph.relation_extraction import extract_relations
from wardline.storage.models.chunks import Chunk
from wardline.storage.models.edges import Edge
from wardline.storage.models.entities import Entity
from wardline.storage.models.entity_resolution import EdgeCandidate, EntityMention

logger = get_logger(__name__)

EDGE_PROMOTION_THRESHOLD = 0.5


def process_document_for_graph(db: Session, doc_id: str) -> dict:
    chunks = list(db.execute(select(Chunk).where(Chunk.doc_id == doc_id)).scalars())
    stats = {"mentions": 0, "edge_candidates": 0, "entities_created": 0, "edges_created": 0, "reviews_queued": 0}

    for chunk in chunks:
        mentions = extract_mentions(chunk.text)
        if not mentions:
            continue

        mention_rows: list[tuple[Mention, EntityMention]] = []
        for m in mentions:
            row = EntityMention(
                chunk_id=chunk.id,
                span_text=m.span_text,
                span_start=m.span_start,
                span_end=m.span_end,
                ner_type=m.ner_type,
                confidence=m.confidence,
            )
            db.add(row)
            db.flush()
            mention_rows.append((m, row))
            stats["mentions"] += 1

        relations = extract_relations(chunk.text, mentions)
        mention_row_by_span = {(m.span_start, m.span_end): row for m, row in mention_rows}
        for rel in relations:
            from_row = mention_row_by_span.get((rel.from_mention.span_start, rel.from_mention.span_end))
            to_row = mention_row_by_span.get((rel.to_mention.span_start, rel.to_mention.span_end))
            if from_row is None or to_row is None:
                continue
            db.add(
                EdgeCandidate(
                    from_mention_id=from_row.id,
                    to_mention_id=to_row.id,
                    type=rel.type,
                    evidence_chunk_id=chunk.id,
                    confidence=rel.confidence,
                )
            )
            stats["edge_candidates"] += 1
        db.flush()

        for m, row in mention_rows:
            entity, created, review_queued = _resolve_mention(db, m)
            row.suggested_entity_id = entity.id
            row.status = "resolved"
            if created:
                stats["entities_created"] += 1
            if review_queued:
                stats["reviews_queued"] += 1

    db.flush()
    stats["edges_created"] = _promote_edge_candidates(db, chunks)
    return stats


def _resolve_mention(db: Session, mention: Mention) -> tuple[Entity, bool, bool]:
    key = block_key(mention.ner_type, mention.span_text)
    candidates = list(db.execute(select(Entity).where(Entity.type == mention.ner_type)).scalars())

    best_entity: Entity | None = None
    best_score = 0.0
    for candidate in candidates:
        # cheap short-circuit: still allow alias matches to survive blocking
        if (
            block_key(candidate.type, candidate.canonical_name) != key
            and mention.span_text.lower() not in [a.lower() for a in candidate.aliases]
        ):
            continue
        score = score_pair(mention.span_text, candidate.canonical_name)
        if score > best_score:
            best_score, best_entity = score, candidate

    if best_entity is not None and best_score >= HIGH_CONFIDENCE_THRESHOLD:
        if mention.span_text not in best_entity.aliases and mention.span_text != best_entity.canonical_name:
            best_entity.aliases = [*best_entity.aliases, mention.span_text]
        return best_entity, False, False

    new_entity = Entity(
        type=mention.ner_type, canonical_name=mention.span_text, confidence=mention.confidence
    )
    db.add(new_entity)
    db.flush()
    sync.sync_entity(new_entity)

    if best_entity is not None and best_score >= REVIEW_THRESHOLD:
        queue_for_review(db, new_entity.id, best_entity.id, best_score)
        return new_entity, True, True

    return new_entity, True, False


def _promote_edge_candidates(db: Session, chunks: list[Chunk]) -> int:
    chunk_ids = [c.id for c in chunks]
    if not chunk_ids:
        return 0

    candidates = list(
        db.execute(
            select(EdgeCandidate).where(
                EdgeCandidate.evidence_chunk_id.in_(chunk_ids), EdgeCandidate.status == "pending"
            )
        ).scalars()
    )
    promoted = 0
    for cand in candidates:
        if cand.confidence < EDGE_PROMOTION_THRESHOLD:
            continue
        from_mention = db.get(EntityMention, cand.from_mention_id)
        to_mention = db.get(EntityMention, cand.to_mention_id)
        if not from_mention or not to_mention:
            continue
        if not from_mention.suggested_entity_id or not to_mention.suggested_entity_id:
            continue
        if from_mention.suggested_entity_id == to_mention.suggested_entity_id:
            continue

        existing = list(
            db.execute(
                select(Edge).where(
                    Edge.from_entity_id == from_mention.suggested_entity_id,
                    Edge.to_entity_id == to_mention.suggested_entity_id,
                    Edge.type == cand.type,
                )
            ).scalars()
        )
        if existing:
            edge = existing[0]
            if cand.evidence_chunk_id not in edge.evidence_chunk_ids:
                edge.evidence_chunk_ids = [*edge.evidence_chunk_ids, cand.evidence_chunk_id]
        else:
            edge = Edge(
                from_entity_id=from_mention.suggested_entity_id,
                to_entity_id=to_mention.suggested_entity_id,
                type=cand.type,
                evidence_chunk_ids=[cand.evidence_chunk_id],
                confidence=cand.confidence,
            )
            db.add(edge)
            promoted += 1
        db.flush()
        sync.sync_edge(edge)
        cand.status = "promoted"

    return promoted
