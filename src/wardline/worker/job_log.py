"""Persisted, per-step progress lines for one `IngestionJob` -- the Ops
Console's live "terminal" tail (`GET /v1/admin/connectors/jobs/{id}/log`).

This is a second, user-facing channel alongside the existing structlog
calls in `worker/jobs.py`/`ingestion/pipeline.py`, not a replacement for
them: structlog is this app's own operational log aggregation (console/
OTel), while this table is what a browser polls to show an admin what a
specific job is doing right now. Deliberately simple -- one INSERT per
call, its own `sync_session()` -- this app has no WebSocket/SSE transport
anywhere yet, so the console polls `after_id` rather than this module
pushing anything.
"""

from __future__ import annotations

from wardline.storage.db import sync_session
from wardline.storage.models.ingestion import JobLogLine


def log_job_event(job_id: str, message: str, level: str = "info") -> None:
    with sync_session() as db:
        db.add(JobLogLine(job_id=job_id, message=message, level=level))
        db.flush()
