"""Typed relations between entities (report 5.3 Edge), each provenance-linked
to the chunks that support it. Canonical in Postgres; mirrored into Neo4j as
relationships by graph/sync.py.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class Edge(Base, TimestampMixin):
    __tablename__ = "edges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "edge"))
    from_entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # FOUNDED | SUBSIDIARY_OF | ...
    evidence_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_edges_from_entity_id", "from_entity_id"),
        Index("ix_edges_to_entity_id", "to_entity_id"),
        Index("ix_edges_type", "type"),
    )
