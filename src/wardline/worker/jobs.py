"""Claim-and-run logic for `ingestion_jobs`, using Postgres `SELECT ... FOR
UPDATE SKIP LOCKED` so multiple worker replicas never double-process a job —
the report's Kafka-consumer-group guarantee, achieved without Kafka.
"""

from __future__ import annotations

import os
import traceback
from datetime import timedelta

from sqlalchemy import select

from wardline.common.logging import get_logger
from wardline.storage.db import sync_session
from wardline.storage.models.base import utcnow
from wardline.storage.models.ingestion import IngestionJob
from wardline.worker.job_log import log_job_event

logger = get_logger(__name__)

_WORKER_ID = f"worker-{os.getpid()}"


def reap_stale_jobs(older_than_seconds: int) -> int:
    """Reclaims jobs stuck `"running"` past `older_than_seconds` -- normally
    a rare, worker-crash-only scenario (this codebase has never had a reaper;
    a dead worker's claimed job just sat "running" forever, same weakness
    kafka_queue.py's own docstring already admits). Made routine, not rare,
    by cron.py's dispatch-jobs endpoint: a job still executing when Vercel
    kills the invocation for running past its time budget has no other
    invocation able to reclaim it otherwise, since claim_next_job() only
    ever selects `status == "pending"`. Marks reclaimed jobs "failed" with a
    clear cause rather than silently re-queuing them as "pending" -- a job
    that was killed mid-run left partial side effects (documents partially
    ingested, etc.), so a plain retry isn't obviously safe; an operator
    (or the connector's own re-run) is a better call than an automatic
    unbounded retry loop.
    """
    cutoff = utcnow() - timedelta(seconds=older_than_seconds)
    with sync_session() as db:
        stmt = select(IngestionJob).where(
            IngestionJob.status == "running", IngestionJob.locked_at < cutoff
        )
        stale = db.execute(stmt).scalars().all()
        for job in stale:
            job.status = "failed"
            job.finished_at = utcnow()
            job.error = (
                f"reclaimed: still \"running\" after {older_than_seconds}s "
                f"(locked_by={job.locked_by!r}, locked_at={job.locked_at}) -- "
                "the invocation that claimed it likely hit a timeout"
            )
            log_job_event(job.id, job.error, level="error")
        db.flush()
        return len(stale)


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
    log_job_event(job.id, f"started ({job.connector_name})")
    try:
        connector = get_connector(job.connector_name, config=resolve_connector_config(job.connector_name))
        result = run_connector_job(connector, job.params, job_id=job.id)
        _finish(job.id, status="succeeded", result=result)
        logger.info("job.succeeded", job_id=job.id, result=result)
        log_job_event(job.id, f"succeeded: {result}")
    except Exception as exc:  # worker must never crash on a bad job
        logger.error("job.failed", job_id=job.id, error=str(exc))
        _finish(job.id, status="failed", error=f"{exc}\n{traceback.format_exc()}")
        log_job_event(job.id, f"failed: {exc}", level="error")


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
