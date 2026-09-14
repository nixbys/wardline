"""Unit coverage for retrieval/feedback_signal.py. `_aggregate_ratings` is
pure (plain tuples in, a dict out) and tested directly; the SQL fetch in
`refresh_trust_scores` needs real Postgres JSONB support and isn't unit-
tested here, matching how lexical_search/vector_search's own Postgres-
specific SQL isn't unit-tested against sqlite elsewhere in this suite.
"""

from __future__ import annotations

from wardline.common.config import Settings, get_settings
from wardline.retrieval import feedback_signal
from wardline.retrieval.feedback_signal import (
    MAX_ADJUSTMENT,
    _aggregate_ratings,
    get_trust_multiplier,
)


def _settings_with(**overrides) -> Settings:
    base = get_settings()
    return Settings(**{**base.model_dump(), **overrides})


def test_no_ratings_yields_no_scores():
    assert _aggregate_ratings([]) == {}


def test_all_positive_ratings_push_the_score_up_but_never_past_the_bound():
    # 10+ votes saturates confidence to 1.0, so this hits the bound exactly.
    rows = [("doc_1", 1)] * 12
    scores = _aggregate_ratings(rows)
    assert scores["doc_1"] == 1.0 + MAX_ADJUSTMENT


def test_all_negative_ratings_push_the_score_down_but_never_past_the_bound():
    rows = [("doc_1", -1)] * 12
    scores = _aggregate_ratings(rows)
    assert scores["doc_1"] == 1.0 - MAX_ADJUSTMENT


def test_mixed_ratings_average_out():
    rows = [("doc_1", 1)] * 5 + [("doc_1", -1)] * 5
    scores = _aggregate_ratings(rows)
    assert scores["doc_1"] == 1.0  # average rating is 0 -- no adjustment either way


def test_a_single_vote_is_damped_by_low_confidence():
    # One vote out of a 10-vote saturation point -> confidence 0.1, so the
    # adjustment is a tenth of the full bound, not the full +/-20%.
    scores = _aggregate_ratings([("doc_1", 1)])
    assert scores["doc_1"] == 1.0 + (MAX_ADJUSTMENT * 0.1)


def test_documents_are_scored_independently():
    rows = [("doc_up", 1), ("doc_down", -1)]
    scores = _aggregate_ratings(rows)
    assert scores["doc_up"] > 1.0
    assert scores["doc_down"] < 1.0


def test_get_trust_multiplier_is_a_no_op_when_apply_is_disabled(monkeypatch):
    monkeypatch.setattr(feedback_signal, "_trust_cache", {"doc_1": 1.2})
    monkeypatch.setattr(feedback_signal, "get_settings", lambda: _settings_with(retrieval_feedback_apply_enabled=False))
    assert get_trust_multiplier("doc_1") == 1.0


def test_get_trust_multiplier_applies_the_cached_score_when_enabled(monkeypatch):
    monkeypatch.setattr(feedback_signal, "_trust_cache", {"doc_1": 1.2})
    monkeypatch.setattr(feedback_signal, "get_settings", lambda: _settings_with(retrieval_feedback_apply_enabled=True))
    assert get_trust_multiplier("doc_1") == 1.2


def test_get_trust_multiplier_defaults_to_a_no_op_for_an_unscored_document(monkeypatch):
    monkeypatch.setattr(feedback_signal, "_trust_cache", {})
    monkeypatch.setattr(feedback_signal, "get_settings", lambda: _settings_with(retrieval_feedback_apply_enabled=True))
    assert get_trust_multiplier("doc_unknown") == 1.0
