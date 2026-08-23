"""Claim-and-run logic for `ingestion_jobs`, using Postgres `SELECT ... FOR
UPDATE SKIP LOCKED` so multiple worker replicas never double-process a job —
the report's Kafka-consumer-group guarantee, achieved without Kafka.
"""

from __future__ import annotations

import os
import traceback

from sqlalchemy import select

from wardline.common.logging import get_logger
from wardline.storage.db import sync_session
from wardline.storage.models.base import utcnow
from wardline.storage.models.ingestion import IngestionJob

logger = get_logger(__name__)

_WORKER_ID = f"worker-{os.getpid()}"


def claim_next_job() -> IngestionJob | None:
    with sync_session() as db:
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.status == "pending")
            .order_by(IngestionJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.execute(stmt).scalars().first()
        if job is None:
            return None
        job.status = "running"
        job.started_at = utcnow()
        job.locked_by = _WORKER_ID
        job.locked_at = utcnow()
        db.flush()
        db.expunge(job)
        return job


def claim_job_by_id(job_id: str) -> IngestionJob | None:
    """Kafka consume path (kafka_queue.py): the message already carries the
    job_id (the API route created the row before publishing), so this just
    marks it running -- same FOR UPDATE guard as claim_next_job, here as a
    second line of defense against ever double-running one job if a
    message is redelivered after a crash. Returns None (a no-op, not an
    error) if the job isn't "pending" anymore -- exactly the redelivery
    case.
    """
    with sync_session() as db:
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.status == "pending")
            .with_for_update(skip_locked=True)
        )
        job = db.execute(stmt).scalars().first()
        if job is None:
            return None
        job.status = "running"
        job.started_at = utcnow()
        job.locked_by = _WORKER_ID
        job.locked_at = utcnow()
        db.flush()
        db.expunge(job)
        return job


def run_job(job: IngestionJob) -> None:
    from wardline.connectors.config import resolve_connector_config
    from wardline.connectors.registry import get_connector
    from wardline.ingestion.pipeline import run_connector_job

    logger.info("job.start", job_id=job.id, connector=job.connector_name)
    try:
        connector = get_connector(job.connector_name, config=resolve_connector_config(job.connector_name))
        result = run_connector_job(connector, job.params)
        _finish(job.id, status="succeeded", result=result)
        logger.info("job.succeeded", job_id=job.id, result=result)
    except Exception as exc:  # worker must never crash on a bad job
        logger.error("job.failed", job_id=job.id, error=str(exc))
        _finish(job.id, status="failed", error=f"{exc}\n{traceback.format_exc()}")


def _finish(job_id: str, *, status: str, result: dict | None = None, error: str | None = None) -> None:
    with sync_session() as db:
        job = db.get(IngestionJob, job_id)
        if job is None:
            return
        job.status = status
        job.finished_at = utcnow()
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
