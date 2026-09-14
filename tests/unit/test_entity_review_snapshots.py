"""Unit coverage for review.queue_for_review's name/type snapshotting --
see EntityResolutionReview's own docstring for why this exists: entity_b's
row (and its canonical_name) is gone by the time a "merged" decision's row
could otherwise be read back.

Uses a fake Entity-like stand-in (not the real ORM model) so this doesn't
need the `entities` table's Postgres-only JSONB columns (`aliases`,
`attributes`) to exist under sqlite -- `db.get` is monkeypatched on the
session instance instead, which Python allows for a plain attribute
override. EntityResolutionReview itself has no JSONB columns, so its own
table is created for real.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.graph.entity_resolution import review
from wardline.storage.models.base import Base
from wardline.storage.models.entity_resolution import EntityResolutionReview


class _FakeEntity:
    def __init__(self, canonical_name: str, type_: str):
        self.canonical_name = canonical_name
        self.type = type_


def _db_with_entities(monkeypatch, entities: dict):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[EntityResolutionReview.__table__])
    db = Session(engine)
    monkeypatch.setattr(db, "get", lambda model, id_: entities.get(id_))
    return db


def test_queue_for_review_snapshots_both_names_and_the_shared_type(monkeypatch):
    db = _db_with_entities(
        monkeypatch,
        {"ent_a": _FakeEntity("Airbnb", "Organization"), "ent_b": _FakeEntity("AirBnB Inc", "Organization")},
    )
    result = review.queue_for_review(db, "ent_a", "ent_b", 0.8)
    assert result.entity_a_name == "Airbnb"
    assert result.entity_b_name == "AirBnB Inc"
    assert result.entity_type == "Organization"
    assert result.score == 0.8
    assert result.status == "pending"


def test_queue_for_review_survives_a_missing_entity_without_crashing(monkeypatch):
    # Defensive: if a caller ever passes a stale id, snapshotting degrades
    # to None fields rather than raising -- the review row itself (and the
    # decision it awaits) still matters even if one name can't be captured.
    db = _db_with_entities(monkeypatch, {"ent_a": _FakeEntity("Airbnb", "Organization")})
    result = review.queue_for_review(db, "ent_a", "ent_missing", 0.8)
    assert result.entity_a_name == "Airbnb"
    assert result.entity_b_name is None
    assert result.entity_type == "Organization"  # falls back to whichever side resolved
