"""Integration test for storage/iceberg_export.py -- the noted Iceberg
upgrade path from "plain Postgres tables + MinIO for raw bytes only" (see
the README's scope-reductions table). Runs against a real Postgres (both
as the source of `audit_events` rows and, via pyiceberg's SqlCatalog, as
the Iceberg catalog itself) and a real local-filesystem Iceberg warehouse
-- genuine append/time-travel/schema-evolution, not a mock of Iceberg's
semantics.
"""

from __future__ import annotations

import uuid

import pytest

from wardline.storage.db import sync_session
from wardline.storage.iceberg_export import _FULL_TABLE, _catalog, export_audit_events
from wardline.storage.models.governance import AuditEvent


@pytest.fixture
def clean_audit_events():
    """Runs against the real audit_events table, tagged with a unique
    session_id so this test's own writes are unambiguous. No teardown
    delete: audit_events enforces append-only at the database level (a
    trigger raises on DELETE/UPDATE -- confirmed by this fixture originally
    attempting one and failing), so a handful of clearly test-tagged rows
    are an expected, permanent, and harmless side effect of running this
    test against a real audit log -- the same as any other real activity.
    """
    return f"test-{uuid.uuid4().hex[:8]}"


def test_export_is_incremental_and_idempotent(clean_audit_events):
    session_id = clean_audit_events

    with sync_session() as db:
        db.add(AuditEvent(session_id=session_id, event_type="query", payload={"q": "first"}))
        db.add(AuditEvent(session_id=session_id, event_type="query", payload={"q": "second"}))

    first = export_audit_events()
    assert first["exported"] >= 2  # >= : other tests/real usage may add rows to the same table

    second = export_audit_events()
    assert second["exported"] == 0  # nothing new since the last export

    with sync_session() as db:
        db.add(AuditEvent(session_id=session_id, event_type="query", payload={"q": "third"}))

    third = export_audit_events()
    assert third["exported"] == 1


def test_real_time_travel_across_snapshots(clean_audit_events):
    session_id = clean_audit_events

    with sync_session() as db:
        db.add(AuditEvent(session_id=session_id, event_type="query", payload={"q": "before"}))
    export_audit_events()

    table = _catalog().load_table(_FULL_TABLE)
    snapshot_before = table.current_snapshot().snapshot_id
    rows_before = table.scan(snapshot_id=snapshot_before).to_arrow().num_rows

    with sync_session() as db:
        db.add(AuditEvent(session_id=session_id, event_type="query", payload={"q": "after"}))
    export_audit_events()

    table = _catalog().load_table(_FULL_TABLE)
    rows_now = table.scan().to_arrow().num_rows
    assert rows_now == rows_before + 1

    # Time travel: the old snapshot still reports the old row count, even
    # though the table has since grown -- this is the actual point of Iceberg
    # over a plain Postgres export.
    assert table.scan(snapshot_id=snapshot_before).to_arrow().num_rows == rows_before
