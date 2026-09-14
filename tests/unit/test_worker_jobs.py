"""Unit coverage for worker/jobs.py:reap_stale_jobs -- the reclaim-a-job-
stuck-"running" logic api/routers/cron.py's dispatch-jobs route needs
(see that route's own docstring for why: routine there, not the rare
worker-crash-only case it is for worker/main.py's persistent loop).

Runs against a real (in-memory SQLite) database, same JSONB compiler-shim
convention as test_accounts.py -- IngestionJob.params/result are Postgres
JSONB columns.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.types import JSON

from wardline.storage.models.base import Base, utcnow
from wardline.storage.models.ingestion import IngestionJob, Source
from wardline.worker import jobs as worker_jobs


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_on_sqlite(element, compiler, **kw):  # pragma: no cover - DDL glue
    return compiler.visit_JSON(JSON(), **kw)


@pytest.fixture()
def sqlite_session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Source.__table__, IngestionJob.__table__])

    @contextmanager
    def _sync_session():
        session = Session(engine)
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(worker_jobs, "sync_session", _sync_session)
    # reap_stale_jobs also calls log_job_event, which opens its own
    # separate sync_session() (worker/job_log.py, not patched above) --
    # that write-through is already covered by test_job_log.py, so this
    # file only needs it to not hit a real DB, not to actually persist.
    monkeypatch.setattr(worker_jobs, "log_job_event", lambda *a, **kw: None)
    return engine


def _seed_source(engine, name="wikipedia"):
    with Session(engine) as db:
        db.add(Source(name=name, default_license="cc-by-sa"))
        db.commit()


def test_reaps_a_job_stuck_running_past_the_threshold(sqlite_session_factory):
    engine = sqlite_session_factory
    _seed_source(engine)
    with Session(engine) as db:
        db.add(
            IngestionJob(
                connector_name="wikipedia",
                status="running",
                locked_by="worker-dead",
                locked_at=utcnow() - timedelta(seconds=1000),
            )
        )
        db.commit()

    reclaimed = worker_jobs.reap_stale_jobs(older_than_seconds=900)
    assert reclaimed == 1

    with Session(engine) as db:
        job = db.query(IngestionJob).one()
    assert job.status == "failed"
    assert job.finished_at is not None
    assert "reclaimed" in job.error
    assert "worker-dead" in job.error


def test_leaves_a_recently_locked_running_job_alone(sqlite_session_factory):
    engine = sqlite_session_factory
    _seed_source(engine)
    with Session(engine) as db:
        db.add(
            IngestionJob(
                connector_name="wikipedia",
                status="running",
                locked_by="worker-alive",
                locked_at=utcnow() - timedelta(seconds=10),
            )
        )
        db.commit()

    reclaimed = worker_jobs.reap_stale_jobs(older_than_seconds=900)
    assert reclaimed == 0

    with Session(engine) as db:
        job = db.query(IngestionJob).one()
    assert job.status == "running"


@pytest.mark.parametrize("status", ["pending", "succeeded", "failed"])
def test_never_touches_non_running_jobs_regardless_of_age(sqlite_session_factory, status):
    engine = sqlite_session_factory
    _seed_source(engine)
    with Session(engine) as db:
        db.add(
            IngestionJob(
                connector_name="wikipedia",
                status=status,
                locked_at=utcnow() - timedelta(seconds=10_000),
            )
        )
        db.commit()

    reclaimed = worker_jobs.reap_stale_jobs(older_than_seconds=900)
    assert reclaimed == 0

    with Session(engine) as db:
        job = db.query(IngestionJob).one()
    assert job.status == status
