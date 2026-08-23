"""Bronze/silver document records — the collection & ingestion planes' output.

Mirrors the report's Document data model (5.3) plus bookkeeping the report
calls for elsewhere: `status`/`quarantine_reason` (4.2 quality gates),
`source_connector` + `blob_key` (4.1 provenance -> where the raw bytes live
in the bronze tier).
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id, utcnow


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "doc"))
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    license: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lang: Mapped[str] = mapped_column(String(16), default="en")

    status: Mapped[str] = mapped_column(String(16), default="active")  # active | quarantined
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_connector: Mapped[str] = mapped_column(String(64), nullable=False)
    blob_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_documents_content_hash", "content_hash"),
        Index("ix_documents_source_connector", "source_connector"),
        Index("ix_documents_status", "status"),
    )
