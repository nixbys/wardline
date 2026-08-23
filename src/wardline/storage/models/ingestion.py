"""Storage-lakehouse catalog (report 4.3) and the ingestion job queue that
substitutes for Kafka/Airflow at single-node scale (see plan's documented
scope reduction): `ingestion_jobs` is polled by worker/main.py with
`SELECT ... FOR UPDATE SKIP LOCKED`.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class Source(Base, TimestampMixin):
    """Catalog entry for a registered connector (report's 'data catalog' 4.3)."""

    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    default_license: Mapped[str] = mapped_column(String(128), nullable=False)
    config_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)


class IngestionJob(Base, TimestampMixin):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "job"))
    connector_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("sources.name", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | running | succeeded | failed
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_ingestion_jobs_status", "status"),
        Index("ix_ingestion_jobs_connector_name", "connector_name"),
    )
