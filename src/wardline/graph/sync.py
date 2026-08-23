"""Mirrors canonical Postgres entities/edges into Neo4j (report 4.5): Postgres
stays the system of record for the entity-resolution review workflow;
Neo4j is the queryable traversal engine the query plane's graph_lookup uses.
"""

from __future__ import annotations

from wardline.graph import repository
from wardline.storage.models.edges import Edge
from wardline.storage.models.entities import Entity


def sync_entity(entity: Entity) -> None:
    repository.upsert_entity(entity.id, entity.type, entity.canonical_name, entity.confidence)


def sync_edge(edge: Edge) -> None:
    repository.upsert_edge(
        edge.id, edge.from_entity_id, edge.to_entity_id, edge.type, edge.confidence, edge.evidence_chunk_ids
    )
