"""Real OpenSearch BM25 lexical retrieval -- the noted upgrade path from
Postgres `tsvector`/`ts_rank_cd` (a BM25-*like* approximation, not true
BM25). Selected via `settings.lexical_backend = "opensearch"`; the
Postgres path (`retrieval/lexical.py`) stays the zero-extra-infra default,
since a handful of documents don't need a second search engine -- this
exists for when ranking fidelity does need to improve without giving up
retrieval entirely if OpenSearch is unavailable.

OpenSearch's `text` field type uses BM25 similarity by default (it's the
Lucene/Elasticsearch/OpenSearch standard, not something this module has to
configure), which is the actual thing the scope-reduction row named --
Postgres's `ts_rank_cd` is a different, coarser ranking function.
"""

from __future__ import annotations

from functools import lru_cache

from wardline.common.config import get_settings
from wardline.common.logging import get_logger
from wardline.retrieval.lexical import RetrievedChunk

logger = get_logger(__name__)

_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},
            "text": {"type": "text"},  # BM25 similarity is the default for "text" fields
            "lang": {"type": "keyword"},
            "status": {"type": "keyword"},
            "published_at": {"type": "date"},
        }
    }
}


@lru_cache
def _client():
    from opensearchpy import OpenSearch

    settings = get_settings()
    return OpenSearch(hosts=[settings.opensearch_url], use_ssl=False, verify_certs=False)


def ensure_index() -> None:
    client = _client()
    index = get_settings().opensearch_index
    if not client.indices.exists(index=index):
        client.indices.create(index=index, body=_INDEX_MAPPING)
        logger.info("opensearch.index_created", index=index)


def index_chunk(
    chunk_id: str, doc_id: str, text: str, lang: str, status: str, published_at
) -> None:
    ensure_index()
    _client().index(
        index=get_settings().opensearch_index,
        id=chunk_id,
        body={
            "doc_id": doc_id,
            "text": text,
            "lang": lang,
            "status": status,
            "published_at": published_at.isoformat() if published_at else None,
        },
        refresh=True,  # this app's write volume is low; immediate searchability matters more
    )


def delete_chunk(chunk_id: str) -> None:
    client = _client()
    index = get_settings().opensearch_index
    if client.indices.exists(index=index):
        client.delete(index=index, id=chunk_id, ignore=[404])


def lexical_search_opensearch(
    query: str, k: int | None = None, filters: dict | None = None
) -> list[RetrievedChunk]:
    settings = get_settings()
    filters = filters or {}
    k = k or settings.lexical_top_k

    must = [{"match": {"text": query}}]
    filter_clauses = [{"term": {"status": "active"}}]
    if filters.get("lang"):
        filter_clauses.append({"term": {"lang": filters["lang"]}})
    if filters.get("published_after"):
        published_after = filters["published_after"]
        published_after = (
            published_after.isoformat() if hasattr(published_after, "isoformat") else published_after
        )
        filter_clauses.append({"range": {"published_at": {"gte": published_after}}})

    client = _client()
    index = settings.opensearch_index
    if not client.indices.exists(index=index):
        return []

    resp = client.search(
        index=index,
        body={"query": {"bool": {"must": must, "filter": filter_clauses}}, "size": k},
    )
    return [
        RetrievedChunk(
            chunk_id=hit["_id"],
            doc_id=hit["_source"]["doc_id"],
            text=hit["_source"]["text"],
            score=float(hit["_score"]),
        )
        for hit in resp["hits"]["hits"]
    ]
