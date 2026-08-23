"""Integration test for the Splink batch entity-resolution pass
(graph/entity_resolution/splink_batch.py) against a real Postgres --
Splink's DuckDB comparison engine is exercised end-to-end, and so is the
ORM-level merge (`review.merge_entities`: aliases, edge/mention repointing,
row deletion), which the module's own unit-level tests can't reach without
a database.

Requires POSTGRES_* env vars pointed at a real, migrated database, same as
every other test in `tests/integration` -- CI's `test` job already
provisions this service container and runs `alembic upgrade head` before
pytest.
"""

from __future__ import annotations

import pytest

from wardline.graph.entity_resolution.review import list_pending
from wardline.graph.entity_resolution.splink_batch import run_batch_resolution
from wardline.storage.db import get_sync_sessionmaker
from wardline.storage.models.entities import Entity


@pytest.fixture
def db_session():
    session = get_sync_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()  # never persist test fixtures past this test
        session.close()


def _make(db_session, type_: str, name: str) -> Entity:
    entity = Entity(type=type_, canonical_name=name)
    db_session.add(entity)
    db_session.flush()
    return entity


def test_batch_resolution_merges_exact_duplicate_and_reviews_near_duplicate(db_session):
    entity_type = "TestPersonBatch"  # unique to this test, won't collide with real data
    exact_a = _make(db_session, entity_type, "Brian Chesky")
    exact_b = _make(db_session, entity_type, "Brian Chesky")
    near_a = _make(db_session, entity_type, "Joe Gebbia")
    near_b = _make(db_session, entity_type, "Joseph Gebbia")
    distinct = [
        _make(db_session, entity_type, n)
        for n in ("Wei Zhang", "Amara Okafor", "Lucas Ferreira", "Priya Natarajan")
    ]
    db_session.flush()

    stats = run_batch_resolution(db_session, entity_type=entity_type)

    assert stats["types_scanned"] == 1
    assert stats["merged"] >= 1
    assert stats["queued_for_review"] >= 1

    # The exact duplicate: one row was merged away, the other absorbed it.
    remaining_ids = {e.id for e in db_session.query(Entity).filter(Entity.type == entity_type)}
    assert not ({exact_a.id, exact_b.id} <= remaining_ids)  # not both still present
    assert len({exact_a.id, exact_b.id} & remaining_ids) == 1  # exactly one survivor

    # The near-duplicate: both rows survive, a review row links them.
    assert {near_a.id, near_b.id} <= remaining_ids
    pending = list_pending(db_session)
    pending_pairs = {frozenset((r.entity_a_id, r.entity_b_id)) for r in pending}
    assert frozenset((near_a.id, near_b.id)) in pending_pairs

    # Unrelated distinct entities were left alone entirely.
    for e in distinct:
        assert e.id in remaining_ids
