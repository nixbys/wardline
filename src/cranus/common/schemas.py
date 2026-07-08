"""Pydantic mirrors of the report's Section 5.3 data models.

These are the wire/contract shapes (API request/response, inter-plane
messages). The SQLAlchemy models in storage/models/ are the persisted shape;
they carry the same fields plus DB bookkeeping (primary keys, timestamps,
foreign keys). Keeping both is deliberate: pydantic here is what the report
specifies verbatim, so a schema snapshot test can catch drift from the spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    uri: str
    fetched_at: datetime
    license: str
    content_hash: str
    source_connector: str


class Document(BaseModel):
    doc_id: str
    uri: str
    title: str
    published_at: datetime | None = None
    fetched_at: datetime
    license: str
    content_hash: str
    lang: str = "en"
    status: Literal["active", "quarantined"] = "active"
    quarantine_reason: str | None = None


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    ordinal: int
    char_start: int
    char_end: int
    embedding_model: str | None = None
    entities: list[str] = Field(default_factory=list)


class Entity(BaseModel):
    entity_id: str
    type: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    confidence: float = 1.0


class Edge(BaseModel):
    edge_id: str
    from_: str = Field(alias="from")
    to: str
    type: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    confidence: float
    valid_from: datetime | None = None

    model_config = {"populate_by_name": True}


class Citation(BaseModel):
    claim_id: str
    supported_by: list[str]


class QuerySession(BaseModel):
    session_id: str
    user_id: str
    question: str
    asked_at: datetime
    retrieved: list[str] = Field(default_factory=list)
    answer_hash: str | None = None
    latency_ms: int | None = None
    token_cost: int | None = None


class SourceRef(BaseModel):
    id: str
    doc_id: str | None = None
    uri: str | None = None
    title: str | None = None
    license: str | None = None
    kind: Literal["chunk", "edge"] = "chunk"


class Claim(BaseModel):
    id: str
    text: str
    supported_by: list[str]


class QueryRequest(BaseModel):
    question: str
    mode: Literal["fast", "auto", "research"] = "auto"
    filters: dict[str, str] = Field(default_factory=dict)
    max_sources: int = 12


class QueryResponse(BaseModel):
    session_id: str
    answer: str
    claims: list[Claim]
    sources: list[SourceRef]
    confidence: float
    insufficient_evidence: bool
    latency_ms: int
