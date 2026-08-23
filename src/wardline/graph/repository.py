"""Neo4j access layer (report 4.5) — raw parametrized Cypher via the official
driver, deliberately not an OGM: relationship types are dynamic
(FOUNDED, SUBSIDIARY_OF, ...), which maps awkwardly onto OGM class
hierarchies.
"""

from __future__ import annotations

from functools import lru_cache

from neo4j import Driver, GraphDatabase

from wardline.common.config import get_settings
from wardline.graph.schema import CONSTRAINTS_CYPHER


@lru_cache
def get_driver() -> Driver:
    settings = get_settings()
    return GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))


def ensure_constraints() -> None:
    with get_driver().session() as session:
        for stmt in CONSTRAINTS_CYPHER:
            session.run(stmt)


def upsert_entity(entity_id: str, entity_type: str, canonical_name: str, confidence: float) -> None:
    with get_driver().session() as session:
        session.run(
            """
            MERGE (e:Entity {id: $id})
            SET e.type = $type, e.canonical_name = $canonical_name, e.confidence = $confidence
            """,
            id=entity_id,
            type=entity_type,
            canonical_name=canonical_name,
            confidence=confidence,
        )


def upsert_edge(
    edge_id: str,
    from_entity_id: str,
    to_entity_id: str,
    rel_type: str,
    confidence: float,
    evidence_chunk_ids: list[str],
) -> None:
    with get_driver().session() as session:
        session.run(
            """
            MATCH (a:Entity {id: $from_id}), (b:Entity {id: $to_id})
            MERGE (a)-[r:RELATION {id: $edge_id}]->(b)
            SET r.type = $rel_type, r.confidence = $confidence, r.evidence_chunk_ids = $evidence
            """,
            from_id=from_entity_id,
            to_id=to_entity_id,
            edge_id=edge_id,
            rel_type=rel_type,
            confidence=confidence,
            evidence=evidence_chunk_ids,
        )


def traverse(entity_id: str, hops: int = 1) -> list[dict]:
    """Return outgoing+incoming relations up to `hops` away, each with the
    neighbor's canonical name and the edge's own properties."""
    with get_driver().session() as session:
        result = session.run(
            f"""
            MATCH (a:Entity {{id: $id}})-[r:RELATION*1..{min(hops, 3)}]-(b:Entity)
            UNWIND r AS rel
            WITH DISTINCT rel, a, b
            MATCH (src)-[rel]->(dst)
            RETURN rel.id AS edge_id, rel.type AS type, rel.confidence AS confidence,
                   rel.evidence_chunk_ids AS evidence_chunk_ids,
                   src.id AS from_id, src.canonical_name AS from_name,
                   dst.id AS to_id, dst.canonical_name AS to_name
            """,
            id=entity_id,
        )
        return [dict(record) for record in result]


def find_entity_by_name(name: str) -> dict | None:
    with get_driver().session() as session:
        result = session.run(
            "MATCH (e:Entity) WHERE toLower(e.canonical_name) = toLower($name) RETURN e LIMIT 1",
            name=name,
        )
        record = result.single()
        return dict(record["e"]) if record else None
