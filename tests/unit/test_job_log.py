"""Unit coverage for worker/job_log.py (log_job_event -- the Ops Console's
live "terminal" tail) and the lifecycle lines worker/jobs.py:run_job writes
around it.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.storage.models.base import Base
from wardline.storage.models.ingestion import JobLogLine
from wardline.worker import job_log


@pytest.fixture()
def sqlite_session_factory(monkeypatch):
    # Only JobLogLine's own table -- IngestionJob/Source use Postgres-only
    # JSONB columns sqlite can't compile, and sqlite doesn't enforce FK
    # integrity by default, so job_id needing no real ingestion_jobs row
    # to exist is fine for what this test actually checks.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[JobLogLine.__table__])

    @contextmanager
    def _sync_session():
        session = Session(engine)
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(job_log, "sync_session", _sync_session)
    return engine


def test_log_job_event_writes_a_row(sqlite_session_factory):
    job_log.log_job_event("job_1", "started (wikipedia)")
    job_log.log_job_event("job_1", "boom", level="error")

    with Session(sqlite_session_factory) as db:
        rows = db.query(JobLogLine).order_by(JobLogLine.id).all()
    assert [r.message for r in rows] == ["started (wikipedia)", "boom"]
    assert [r.level for r in rows] == ["info", "error"]
    assert all(r.job_id == "job_1" for r in rows)


def test_log_job_event_ids_increase_monotonically_for_after_id_polling(sqlite_session_factory):
    job_log.log_job_event("job_1", "one")
    job_log.log_job_event("job_1", "two")
    with Session(sqlite_session_factory) as db:
        rows = db.query(JobLogLine).order_by(JobLogLine.id).all()
    assert rows[0].id < rows[1].id


# --- worker/jobs.py:run_job's lifecycle lines --------------------------


class _FakeJob:
    id = "job_1"
    connector_name = "wikipedia"
    params: dict = {}  # noqa: RUF012 -- a plain stand-in for IngestionJob, not a real dataclass


def test_run_job_logs_start_and_success(monkeypatch):
    from wardline.worker import jobs as worker_jobs

    events = []
    monkeypatch.setattr(worker_jobs, "log_job_event", lambda job_id, msg, level="info": events.append((job_id, msg, level)))
    monkeypatch.setattr(worker_jobs, "_finish", lambda *a, **k: None)
    monkeypatch.setattr("wardline.connectors.config.resolve_connector_config", lambda name: {})
    monkeypatch.setattr("wardline.connectors.registry.get_connector", lambda name, config=None: object())
    monkeypatch.setattr(
        "wardline.ingestion.pipeline.run_connector_job",
        lambda connector, params, job_id=None: {"ingested": 3},
    )

    worker_jobs.run_job(_FakeJob())

    assert events[0] == ("job_1", "started (wikipedia)", "info")
    assert events[1] == ("job_1", "succeeded: {'ingested': 3}", "info")


def test_run_job_logs_failure(monkeypatch):
    from wardline.worker import jobs as worker_jobs

    events = []
    monkeypatch.setattr(worker_jobs, "log_job_event", lambda job_id, msg, level="info": events.append((job_id, msg, level)))
    monkeypatch.setattr(worker_jobs, "_finish", lambda *a, **k: None)
    monkeypatch.setattr("wardline.connectors.config.resolve_connector_config", lambda name: {})
    monkeypatch.setattr("wardline.connectors.registry.get_connector", lambda name, config=None: object())

    def _boom(connector, params, job_id=None):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr("wardline.ingestion.pipeline.run_connector_job", _boom)

    worker_jobs.run_job(_FakeJob())

    assert events[0] == ("job_1", "started (wikipedia)", "info")
    assert events[1][0] == "job_1"
    assert "upstream is down" in events[1][1]
    assert events[1][2] == "error"
