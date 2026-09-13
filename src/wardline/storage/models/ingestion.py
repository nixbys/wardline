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


class JobLogLine(Base, TimestampMixin):
    """Per-step progress lines for one `IngestionJob` (the Ops Console's
    live "terminal" tail — `api/routers/admin_connectors.py`'s
    `GET /jobs/{id}/log?after_id=`). A plain auto-incrementing integer id,
    unlike this codebase's usual `new_id()`-prefixed string ids: cursor-
    based polling needs a strictly-ordered, comparable id ("give me
    everything after N"), which a random id can't provide. Written by
    `worker/job_log.log_job_event` -- see that module for why per-item
    lines are capped rather than unbounded.
    """

    __tablename__ = "job_log_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(16), default="info")  # "info" | "error"
    message: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_job_log_lines_job_id", "job_id"),)
