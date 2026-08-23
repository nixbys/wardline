"""Wires the knowledge graph into the query plane's retrieval planner (report
5.5 step 3c / step 5 "graph expansion"): resolve entities mentioned in the
question, traverse the graph for relevant facts, and pull each fact's
evidence chunks into the candidate set alongside it.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from wardline.common.logging import get_logger
from wardline.graph import repository
from wardline.graph.entity_resolution.scoring import score_pair
from wardline.graph.ner import extract_mentions
from wardline.retrieval.fusion import FusedResult
from wardline.storage.db import sync_session
from wardline.storage.models.chunks import Chunk
from wardline.storage.models.entities import Entity

logger = get_logger(__name__)

ENTITY_MATCH_THRESHOLD = 0.6
GRAPH_FACT_SCORE = 1.0  # graph facts are precise; rank above fuzzy text matches in RRF input

# spaCy's small model frequently tags nothing in short, bare questions ("Who
# founded Airbnb?") — it's tuned for prose with context, not terse queries.
# Capitalized-phrase extraction is a cheap, real fallback so entity matching
# doesn't depend solely on NER succeeding on the question text itself.
_QUESTION_STOPWORDS = {"who", "what", "when", "where", "why", "how", "which", "whom", "did", "does", "is", "are"}
_CAPITALIZED_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)*\b")


def _human_readable(rel_type: str) -> str:
    return rel_type.replace("_", " ").lower()


def _candidate_phrases(question: str) -> list[str]:
    seen: set[str] = set()
    phrases: list[str] = []
    for m in extract_mentions(question):
        if m.span_text.lower() not in seen:
            seen.add(m.span_text.lower())
            phrases.append(m.span_text)
    for match in _CAPITALIZED_PHRASE_RE.finditer(question):
        phrase = match.group().strip()
        if phrase.lower() in _QUESTION_STOPWORDS or phrase.lower() in seen:
            continue
        seen.add(phrase.lower())
        phrases.append(phrase)
    return phrases


def graph_lookup_for_question(question: str, hops: int = 2) -> list[FusedResult]:
    phrases = _candidate_phrases(question)
    if not phrases:
        return []

    results: list[FusedResult] = []
    with sync_session() as db:
        candidates = list(db.execute(select(Entity)).scalars())
        matched_entity_ids: set[str] = set()

        for phrase in phrases:
            best_id, best_score = None, 0.0
            for entity in candidates:
                score = score_pair(phrase, entity.canonical_name)
                if score > best_score:
                    best_score, best_id = score, entity.id
            if best_id and best_score >= ENTITY_MATCH_THRESHOLD:
                matched_entity_ids.add(best_id)

        seen_edges: set[str] = set()
        for entity_id in matched_entity_ids:
            for fact in repository.traverse(entity_id, hops=hops):
                if fact["edge_id"] in seen_edges:
                    continue
                seen_edges.add(fact["edge_id"])
                fact_text = f"{fact['from_name']} {_human_readable(fact['type'])} {fact['to_name']}"
                results.append(
                    FusedResult(
                        chunk_id=fact["edge_id"],
                        doc_id="graph",
                        text=fact_text,
                        rrf_score=GRAPH_FACT_SCORE * (fact.get("confidence") or 0.5),
                    )
                )
                for chunk_id in fact.get("evidence_chunk_ids") or []:
                    chunk = db.get(Chunk, chunk_id)
                    if chunk:
                        results.append(
                            FusedResult(
                                chunk_id=chunk.id,
                                doc_id=chunk.doc_id,
                                text=chunk.text,
                                rrf_score=GRAPH_FACT_SCORE * 0.9,
                            )
                        )

    return results
