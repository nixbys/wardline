"""Retrievable passages (report 5.3 Chunk) — the unit both the lexical and
vector retrievers operate on, and the unit citations point to.

`tsv` is a Postgres generated column (see migrations/versions for the
`wardline_to_tsvector` immutable wrapper function it depends on) so lexical
search never drifts out of sync with `text`. `embedding` is a pgvector column
sized to `settings.embedding_dim`.
"""

from __future__ import annotations

from functools import partial

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from wardline.common.config import get_settings
from wardline.storage.models.base import Base, TimestampMixin, new_id

_EMBEDDING_DIM = get_settings().embedding_dim


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "chunk"))
    doc_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    pii_tags: Mapped[list] = mapped_column(JSONB, default=list)

    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("wardline_to_tsvector(text)", persisted=True), nullable=True
    )

    __table_args__ = (
        Index("ix_chunks_doc_id", "doc_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
