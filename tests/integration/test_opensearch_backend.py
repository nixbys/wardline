"""Integration test for the real OpenSearch BM25 lexical backend
(retrieval/opensearch_backend.py) -- the noted upgrade path from Postgres
tsvector's BM25-*like* ranking (see the README's scope-reductions table).

Requires a real OpenSearch reachable at OPENSEARCH_URL; CI's `test` job
provisions one as a service container. Skips itself otherwise, same as
tests/integration/test_oidc_live.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL")
pytestmark = pytest.mark.skipif(
    not OPENSEARCH_URL, reason="OPENSEARCH_URL not set -- no live OpenSearch to test against"
)


@pytest.fixture
def opensearch_index(monkeypatch):
    """Points opensearch_backend at a throwaway index for this test only, so
    it can't collide with (or be polluted by) any other test run.
    """
    from wardline.common.config import get_settings
    from wardline.retrieval import opensearch_backend

    index_name = f"wardline-chunks-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("OPENSEARCH_INDEX", index_name)
    get_settings.cache_clear()
    opensearch_backend._client.cache_clear()

    yield index_name

    client = opensearch_backend._client()
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
    get_settings.cache_clear()
    opensearch_backend._client.cache_clear()


def test_index_and_search_real_bm25_ranking(opensearch_index):
    from wardline.retrieval.opensearch_backend import index_chunk, lexical_search_opensearch

    index_chunk("c1", "d1", "Acme Corp was founded by Carol in 2010.", "en", "active", datetime(2020, 1, 1, tzinfo=UTC))
    index_chunk("c2", "d1", "Beta Inc makes widgets in a factory.", "en", "active", datetime(2021, 1, 1, tzinfo=UTC))
    index_chunk("c3", "d1", "Unrelated text about gardening and plants.", "en", "active", datetime(2019, 1, 1, tzinfo=UTC))

    results = lexical_search_opensearch("Acme Corp founded", k=5)
    assert [r.chunk_id for r in results] == ["c1"]
    assert results[0].score > 0


def test_filters_are_applied(opensearch_index):
    from wardline.retrieval.opensearch_backend import index_chunk, lexical_search_opensearch

    index_chunk("c1", "d1", "Acme Corp was founded by Carol in 2010.", "en", "active", datetime(2020, 1, 1, tzinfo=UTC))

    assert lexical_search_opensearch("Acme Corp", filters={"lang": "fr"}) == []
    assert lexical_search_opensearch("Acme Corp", filters={"published_after": datetime(2022, 1, 1, tzinfo=UTC)}) == []
    assert len(lexical_search_opensearch("Acme Corp", filters={"lang": "en"})) == 1


def test_lexical_search_dispatches_to_opensearch_when_configured(opensearch_index, monkeypatch):
    """retrieval/lexical.py's public lexical_search() -- what the rest of the
    app actually calls -- must route to OpenSearch when configured, with no
    other code change needed downstream (fusion, rerank, API).
    """
    from wardline.common.config import get_settings
    from wardline.retrieval.opensearch_backend import index_chunk

    monkeypatch.setenv("LEXICAL_BACKEND", "opensearch")
    get_settings.cache_clear()
    try:
        index_chunk("c1", "d1", "Acme Corp was founded by Carol.", "en", "active", None)

        from wardline.retrieval.lexical import lexical_search

        results = lexical_search(db=None, query="Acme Corp founded")  # db unused on this path
        assert [r.chunk_id for r in results] == ["c1"]
    finally:
        monkeypatch.delenv("LEXICAL_BACKEND", raising=False)
        get_settings.cache_clear()
