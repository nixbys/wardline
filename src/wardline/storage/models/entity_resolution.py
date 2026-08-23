"""Staging tables for the knowledge & fusion plane's extraction and
entity-resolution pipeline (report 4.5): raw NER/RE output lands here first;
promotion into canonical `entities`/`edges` only happens after blocking ->
scoring -> clustering, with low-confidence merges routed to human review.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class EntityMention(Base, TimestampMixin):
    """A single NER hit in a chunk, not yet resolved to a canonical entity."""

    __tablename__ = "entity_mentions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "mention"))
    chunk_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    span_text: Mapped[str] = mapped_column(String(512), nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    ner_type: Mapped[str] = mapped_column(String(64), nullable=False)
    suggested_entity_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|resolved|rejected

    __table_args__ = (Index("ix_entity_mentions_chunk_id", "chunk_id"),)


class EdgeCandidate(Base, TimestampMixin):
    """A raw relation-extraction hit, not yet promoted to a canonical Edge."""

    __tablename__ = "edge_candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "edgec"))
    from_mention_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("entity_mentions.id", ondelete="CASCADE"), nullable=False
    )
    to_mention_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("entity_mentions.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_chunk_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|promoted|rejected

    __table_args__ = (Index("ix_edge_candidates_status", "status"),)


class EntityResolutionReview(Base, TimestampMixin):
    """A candidate merge pair surfaced by blocking+scoring, awaiting human review
    (or auto-decided if confidence clears the high-confidence threshold)."""

    __tablename__ = "entity_resolution_review"

    # SET NULL, not CASCADE: a merge decision deletes the "drop" entity, and this
    # row IS the audit record of that decision — cascading would delete the
    # record of the merge at the exact moment the merge happens.
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "review"))
    entity_a_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    entity_b_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|merged|rejected
    decided_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_entity_resolution_review_status", "status"),)
