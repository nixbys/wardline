"""Unit coverage for api/routers/admin_graph.py. `graph/repository.py`
talks to a real Neo4j driver, so these mock at that boundary (monkeypatch
the `repository` module the router imports) rather than standing up a
live graph -- there's no Neo4j-testcontainer convention elsewhere in this
suite to match, and the router's own job here is just response shaping,
not the Cypher itself (repository.py's own correctness is a separate
concern from whether this route calls it correctly and handles a miss).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from wardline.api.routers import admin_graph


def test_search_entity_returns_the_match(monkeypatch):
    monkeypatch.setattr(
        admin_graph.repository,
        "find_entity_by_name",
        lambda name: {"id": "ent_1", "canonical_name": name},
    )
    result = admin_graph.search_entity(name="Airbnb", _user=None)
    assert result == {"id": "ent_1", "canonical_name": "Airbnb"}


def test_search_entity_404s_on_no_match(monkeypatch):
    monkeypatch.setattr(admin_graph.repository, "find_entity_by_name", lambda name: None)
    with pytest.raises(HTTPException) as exc_info:
        admin_graph.search_entity(name="Nobody", _user=None)
    assert exc_info.value.status_code == 404


def test_traverse_entity_passes_hops_through(monkeypatch):
    captured = {}

    def fake_traverse(entity_id, hops=1):
        captured["entity_id"] = entity_id
        captured["hops"] = hops
        return [{"edge_id": "e1", "type": "FOUNDED"}]

    monkeypatch.setattr(admin_graph.repository, "traverse", fake_traverse)
    result = admin_graph.traverse_entity(entity_id="ent_1", hops=2, _user=None)
    assert result == [{"edge_id": "e1", "type": "FOUNDED"}]
    assert captured == {"entity_id": "ent_1", "hops": 2}
