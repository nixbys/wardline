"""Integration test for ingestion/pipeline.py's Prefect refactor (the
report's noted Airflow/Prefect/Dagster upgrade path). Runs the real
ingest_item/run_connector_job flows against a real Postgres, using
Prefect's own test harness for an isolated ephemeral run store -- this is
the actual pipeline every connector goes through, not a mock of it, so a
regression in the fetch->parse->persist->index->graph-process sequence
(or in how it's wired into Prefect tasks/flows) would show up here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from prefect.testing.utilities import prefect_test_harness

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.ingestion.pipeline import ingest_item, run_connector_job
from wardline.storage.db import get_sync_sessionmaker
from wardline.storage.models.documents import Document


class _FakeConnector(Connector):
    """Yields one fixed document; `default_license` must be one
    quality_gates.KNOWN_LICENSES recognizes.
    """

    name = "fake_test_connector"
    default_license = "CC0-1.0"

    def __init__(self, text: str = "Acme Corp was founded by Carol back in 2010."):
        super().__init__()
        self._text = text

    async def discover(self, **kwargs) -> AsyncIterator[SourceItem]:
        yield SourceItem(ref="fake://doc-1")

    async def fetch(self, item: SourceItem) -> RawObject:
        return RawObject(
            uri=item.ref,
            content=self._text.encode("utf-8"),
            content_type="text/plain",
            fetched_at=datetime.now(UTC),
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        return ParsedDocument(uri=raw.uri, title="Fake Doc", text=raw.content.decode("utf-8"))


@pytest.fixture(scope="module", autouse=True)
def _isolated_prefect():
    with prefect_test_harness():
        yield


def _cleanup(doc_ids: list[str]) -> None:
    if not doc_ids:
        return
    session = get_sync_sessionmaker()()
    try:
        for doc_id in doc_ids:
            doc = session.get(Document, doc_id)
            if doc is not None:
                session.delete(doc)
        session.commit()
    finally:
        session.close()


async def test_ingest_item_runs_the_real_pipeline_end_to_end():
    connector = _FakeConnector()
    item = SourceItem(ref="fake://doc-1")
    doc_ids: list[str] = []
    try:
        result = await ingest_item(connector, item)
        assert result["status"] == "ingested"
        doc_ids.append(result["doc_id"])

        session = get_sync_sessionmaker()()
        try:
            doc = session.get(Document, result["doc_id"])
            assert doc is not None
            assert doc.status == "active"
        finally:
            session.close()

        # Same content again -> the duplicate-detection subflow, not a re-ingest.
        second = await ingest_item(connector, item)
        assert second["status"] == "duplicate"
        assert second["doc_id"] == result["doc_id"]
    finally:
        _cleanup(doc_ids)


def test_run_connector_job_flow_discovers_and_ingests():
    connector = _FakeConnector(text="Distinct content for the job-level flow test.")
    doc_ids: list[str] = []
    try:
        stats = run_connector_job(connector, {})
        assert stats["discovered"] == 1
        assert stats["ingested"] == 1
        assert stats["errors"] == 0

        session = get_sync_sessionmaker()()
        try:
            doc = (
                session.query(Document)
                .filter(Document.uri == "fake://doc-1", Document.source_connector == connector.name)
                .order_by(Document.created_at.desc())
                .first()
            )
            assert doc is not None
            doc_ids.append(doc.id)
        finally:
            session.close()
    finally:
        _cleanup(doc_ids)
