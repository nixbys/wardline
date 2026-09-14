"""Serverless-friendly stand-in for worker/main.py's persistent loop, for
deployment targets that can't run a long-lived process (e.g. Vercel --
see docs/VERCEL_DEPLOYMENT.md). A normal docker-compose deployment never
calls these: worker/main.py's `while True` loop + APScheduler still do the
same work there, unchanged, and remain the primary mechanism.

Guarded by CRON_SECRET rather than the usual RBAC (require_role) -- a
cron caller isn't a wardline user/API key holder, so it doesn't fit that
model. Named to match Vercel's own convention: when a project env var of
exactly this name is set, Vercel automatically sends `Authorization:
Bearer $CRON_SECRET` on every cron-triggered request. Every route here
404s (not 403 -- see _require_cron_secret's own reasoning) when
CRON_SECRET isn't configured, so these endpoints are inert by default.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException

from wardline.common.config import get_settings
from wardline.common.logging import get_logger

router = APIRouter(prefix="/v1/cron", tags=["cron"])
logger = get_logger(__name__)


def _require_cron_secret(authorization: str | None) -> None:
    settings = get_settings()
    if not settings.cron_secret:
        # 404, not 403: an unconfigured deployment (every docker-compose one)
        # shouldn't even reveal that this route exists -- it's not a
        # feature that's "off", it's a route this deployment target never
        # uses at all.
        raise HTTPException(status_code=404, detail="not found")
    expected = f"Bearer {settings.cron_secret}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid or missing cron secret")


@router.get("/dispatch-jobs")
def dispatch_jobs(authorization: str | None = Header(default=None)) -> dict:
    """Replaces worker/main.py's job-processing loop. Reclaims any job
    stuck "running" past cron_stale_job_timeout_seconds first (see
    worker.jobs.reap_stale_jobs's own docstring for why that's required
    here, not optional), then claims+runs jobs until the queue is empty or
    the configured time budget is used up."""
    _require_cron_secret(authorization)
    settings = get_settings()

    from wardline.worker.jobs import claim_next_job, reap_stale_jobs, run_job

    reclaimed = reap_stale_jobs(settings.cron_stale_job_timeout_seconds)

    started = time.monotonic()
    ran = 0
    while time.monotonic() - started < settings.cron_dispatch_budget_seconds:
        job = claim_next_job()
        if job is None:
            break
        run_job(job)
        ran += 1

    return {"reclaimed_stale": reclaimed, "ran": ran}


@router.get("/entity-resolution")
def entity_resolution(authorization: str | None = Header(default=None)) -> dict:
    """Replaces worker/main.py's periodic "entity-resolution-batch" job.
    worker/main.py only ever *registers* this job when
    entity_resolution_batch_enabled is set -- run_scheduled_batch_resolution
    itself has no internal check, so this route mirrors that gate rather
    than relying on the function to enforce it."""
    _require_cron_secret(authorization)
    if not get_settings().entity_resolution_batch_enabled:
        return {"ok": True, "skipped": "entity_resolution_batch_enabled is false"}

    from wardline.graph.entity_resolution.splink_batch import run_scheduled_batch_resolution

    run_scheduled_batch_resolution()
    return {"ok": True}


@router.get("/iceberg-export")
def iceberg_export(authorization: str | None = Header(default=None)) -> dict:
    """Replaces worker/main.py's periodic "iceberg-audit-export" job. Same
    registration-only-gates-it reasoning as entity_resolution above."""
    _require_cron_secret(authorization)
    if not get_settings().iceberg_export_enabled:
        return {"ok": True, "skipped": "iceberg_export_enabled is false"}

    from wardline.storage.iceberg_export import export_audit_events

    export_audit_events()
    return {"ok": True}


@router.get("/feedback-refresh")
def feedback_refresh(authorization: str | None = Header(default=None)) -> dict:
    """Replaces worker/main.py's periodic "retrieval-feedback-refresh" job."""
    _require_cron_secret(authorization)

    from wardline.retrieval.feedback_signal import run_scheduled_trust_refresh

    run_scheduled_trust_refresh()
    return {"ok": True}
