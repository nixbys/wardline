"""Unit coverage for splink_batch.py's Phase 5 training pieces
(_train_m_probabilities, _labeled_merge_pairs). Real Splink/DuckDB/pandas,
no Postgres needed -- unlike the module's own `_predict_pairs`-driven
batch pass (tested against a real Postgres in tests/integration/
test_splink_batch.py, since that path also exercises the ORM-level merge),
training runs entirely against a throwaway in-memory linker built from
plain (name_a, name_b) tuples, so it's genuinely unit-testable.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.graph.entity_resolution.splink_batch import (
    _M_PROBABILITIES,
    _labeled_merge_pairs,
    _train_m_probabilities,
)
from wardline.storage.models.base import Base
from wardline.storage.models.entity_resolution import EntityResolutionReview


def test_train_m_probabilities_returns_none_for_no_pairs():
    assert _train_m_probabilities([]) is None


def test_train_m_probabilities_returns_one_value_per_comparison_level():
    pairs = [
        ("John Smith", "John Smith"),
        ("Jane Doe", "Jane Doe"),
        ("Robert Lee", "Rob Lee"),
        ("Amy Chen", "Amy Chen"),
    ]
    trained = _train_m_probabilities(pairs)
    assert trained is not None
    assert len(trained) == len(_M_PROBABILITIES)  # [exact, >=0.9, >=0.7, else]
    # Splink normalizes trained m-probabilities to sum to (approximately) 1
    # across the levels it could actually observe -- a basic sanity check
    # that real training happened, not that a specific value came back
    # (which would be too brittle against a 4-pair sample).
    assert all(0.0 <= v <= 1.0 for v in trained)


def test_train_m_probabilities_never_raises_on_bad_input():
    # A None name would blow up Splink's SQL -- must degrade to None, not
    # crash the batch pass that called it.
    assert _train_m_probabilities([(None, None)]) is None


def _review_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[EntityResolutionReview.__table__])
    return Session(engine)


def _review(status, entity_type, name_a=None, name_b=None, score=0.8):
    return EntityResolutionReview(
        entity_a_id="a", entity_b_id="b", entity_a_name=name_a, entity_b_name=name_b,
        entity_type=entity_type, score=score, status=status,
    )


def test_labeled_merge_pairs_only_returns_merged_status():
    db = _review_db()
    db.add(_review("merged", "Person", "John Smith", "Jon Smith"))
    db.add(_review("rejected", "Person", "Jane Doe", "Jane Roe"))
    db.add(_review("pending", "Person", "Amy Chen", "Amy Chan"))
    db.flush()

    pairs = _labeled_merge_pairs(db, "Person")
    assert pairs == [("John Smith", "Jon Smith")]


def test_labeled_merge_pairs_filters_by_entity_type():
    db = _review_db()
    db.add(_review("merged", "Person", "John Smith", "Jon Smith"))
    db.add(_review("merged", "Organization", "Acme Inc", "Acme Incorporated"))
    db.flush()

    assert _labeled_merge_pairs(db, "Person") == [("John Smith", "Jon Smith")]
    assert _labeled_merge_pairs(db, "Organization") == [("Acme Inc", "Acme Incorporated")]


def test_labeled_merge_pairs_skips_rows_with_a_missing_name_snapshot():
    # Reviews queued before this migration (or where queue_for_review
    # couldn't resolve one side) shouldn't feed a half-complete pair into
    # training.
    db = _review_db()
    db.add(_review("merged", "Person", "John Smith", None))
    db.flush()

    assert _labeled_merge_pairs(db, "Person") == []
