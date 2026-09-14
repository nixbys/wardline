"""Unit coverage for api/routers/cron.py -- the serverless-friendly stand-in
for worker/main.py's persistent loop (see that router's own docstring).
Route functions are called directly, matching test_admin_graph.py/
test_admin_billing.py's convention; the module-level lazy `from
wardline.worker.jobs import ...`-style imports inside each route are
patched at their origin module (wardline.worker.jobs, etc.), which a fresh
`from X import Y` picks up at call time either way.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from wardline.api.routers import cron
from wardline.common.config import Settings, get_settings


def _settings_with(**overrides) -> Settings:
    base = get_settings()
    return Settings(**{**base.model_dump(), **overrides})


@pytest.fixture()
def configured(monkeypatch):
    """cron_secret set -- the routes are "live" for these tests."""
    monkeypatch.setattr(cron, "get_settings", lambda: _settings_with(cron_secret="s3cr3t"))


def test_every_route_404s_when_cron_secret_is_unset(monkeypatch):
    monkeypatch.setattr(cron, "get_settings", lambda: _settings_with(cron_secret=None))
    for route in (cron.dispatch_jobs, cron.entity_resolution, cron.iceberg_export, cron.feedback_refresh):
        with pytest.raises(HTTPException) as exc_info:
            route(authorization="Bearer whatever")
        assert exc_info.value.status_code == 404


def test_wrong_or_missing_bearer_401s(configured):
    with pytest.raises(HTTPException) as exc_info:
        cron.dispatch_jobs(authorization="Bearer wrong")
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        cron.dispatch_jobs(authorization=None)
    assert exc_info.value.status_code == 401


# --- dispatch-jobs -----------------------------------------------------


def test_dispatch_jobs_reaps_stale_then_claims_until_queue_empty(monkeypatch, configured):
    import wardline.worker.jobs as worker_jobs

    monkeypatch.setattr(cron, "get_settings", lambda: _settings_with(cron_secret="s3cr3t"))
    monkeypatch.setattr(worker_jobs, "reap_stale_jobs", lambda seconds: 2)

    remaining = ["job_a", "job_b"]

    def fake_claim():
        return remaining.pop(0) if remaining else None

    ran = []
    monkeypatch.setattr(worker_jobs, "claim_next_job", fake_claim)
    monkeypatch.setattr(worker_jobs, "run_job", lambda job: ran.append(job))

    result = cron.dispatch_jobs(authorization="Bearer s3cr3t")
    assert result == {"reclaimed_stale": 2, "ran": 2}
    assert ran == ["job_a", "job_b"]


def test_dispatch_jobs_stops_at_the_time_budget_even_with_jobs_still_pending(monkeypatch):
    import wardline.worker.jobs as worker_jobs

    # A budget of 0 means the loop's own `elapsed < budget` check is false
    # before it ever claims a first job -- deterministic, no real sleeping.
    monkeypatch.setattr(
        cron, "get_settings", lambda: _settings_with(cron_secret="s3cr3t", cron_dispatch_budget_seconds=0)
    )
    monkeypatch.setattr(worker_jobs, "reap_stale_jobs", lambda seconds: 0)
    monkeypatch.setattr(worker_jobs, "claim_next_job", lambda: "job_a")  # would loop forever if called
    monkeypatch.setattr(worker_jobs, "run_job", lambda job: None)

    result = cron.dispatch_jobs(authorization="Bearer s3cr3t")
    assert result == {"reclaimed_stale": 0, "ran": 0}


# --- entity-resolution / iceberg-export: gated the same way worker/main.py
# only *registers* them when their *_enabled setting is on -----------------


def test_entity_resolution_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(
        cron, "get_settings", lambda: _settings_with(cron_secret="s3cr3t", entity_resolution_batch_enabled=False)
    )
    called = []
    import wardline.graph.entity_resolution.splink_batch as splink_batch

    monkeypatch.setattr(splink_batch, "run_scheduled_batch_resolution", lambda: called.append(1))

    result = cron.entity_resolution(authorization="Bearer s3cr3t")
    assert result["skipped"]
    assert called == []


def test_entity_resolution_runs_when_enabled(monkeypatch):
    monkeypatch.setattr(
        cron, "get_settings", lambda: _settings_with(cron_secret="s3cr3t", entity_resolution_batch_enabled=True)
    )
    called = []
    import wardline.graph.entity_resolution.splink_batch as splink_batch

    monkeypatch.setattr(splink_batch, "run_scheduled_batch_resolution", lambda: called.append(1))

    result = cron.entity_resolution(authorization="Bearer s3cr3t")
    assert result == {"ok": True}
    assert called == [1]


def test_iceberg_export_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(
        cron, "get_settings", lambda: _settings_with(cron_secret="s3cr3t", iceberg_export_enabled=False)
    )
    called = []
    import wardline.storage.iceberg_export as iceberg_export

    monkeypatch.setattr(iceberg_export, "export_audit_events", lambda: called.append(1))

    result = cron.iceberg_export(authorization="Bearer s3cr3t")
    assert result["skipped"]
    assert called == []


def test_iceberg_export_runs_when_enabled(monkeypatch):
    monkeypatch.setattr(
        cron, "get_settings", lambda: _settings_with(cron_secret="s3cr3t", iceberg_export_enabled=True)
    )
    called = []
    import wardline.storage.iceberg_export as iceberg_export

    monkeypatch.setattr(iceberg_export, "export_audit_events", lambda: called.append(1))

    result = cron.iceberg_export(authorization="Bearer s3cr3t")
    assert result == {"ok": True}
    assert called == [1]


# --- feedback-refresh: always runs, no enabled gate (matches worker/main.py's
# own "always registered" reasoning for this one) --------------------------


def test_feedback_refresh_always_runs(monkeypatch, configured):
    called = []
    import wardline.retrieval.feedback_signal as feedback_signal

    monkeypatch.setattr(feedback_signal, "run_scheduled_trust_refresh", lambda: called.append(1))

    result = cron.feedback_refresh(authorization="Bearer s3cr3t")
    assert result == {"ok": True}
    assert called == [1]
