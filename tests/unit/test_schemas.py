"""Contract tests: the pydantic schemas must keep the exact fields the
report's Section 5.3 data models specify, so drift from the spec is caught
in review rather than discovered later.
"""

from wardline.common.schemas import Chunk, Citation, Document, Edge, Entity, QuerySession


def _fields(model) -> set[str]:
    return set(model.model_fields.keys())


def test_document_fields_match_report_spec():
    assert _fields(Document) == {
        "doc_id", "uri", "title", "published_at", "fetched_at", "license",
        "content_hash", "lang", "status", "quarantine_reason",
    }


def test_chunk_fields_match_report_spec():
    assert _fields(Chunk) == {
        "chunk_id", "doc_id", "text", "ordinal", "char_start", "char_end",
        "embedding_model", "entities",
    }


def test_entity_fields_match_report_spec():
    assert _fields(Entity) == {
        "entity_id", "type", "canonical_name", "aliases", "attributes", "confidence",
    }


def test_edge_fields_match_report_spec():
    edge = Edge(edge_id="edge_1", **{"from": "ent_1"}, to="ent_2", type="FOUNDED", confidence=0.9)
    assert edge.from_ == "ent_1"
    assert _fields(Edge) == {
        "edge_id", "from_", "to", "type", "evidence_chunk_ids", "confidence", "valid_from",
    }


def test_citation_fields_match_report_spec():
    assert _fields(Citation) == {"claim_id", "supported_by"}


def test_query_session_fields_match_report_spec():
    assert _fields(QuerySession) == {
        "session_id", "user_id", "question", "asked_at", "retrieved",
        "answer_hash", "latency_ms", "token_cost",
    }
