"""Orchestrates discover -> fetch -> parse -> normalize -> quality-gate ->
persist for one connector job (report 4.1/4.2). Chunking + embedding happen
separately in retrieval/index.py once a document is durably stored — keeping
"acquire and store" and "make retrievable" as distinct steps mirrors the
report's collection-plane vs. retrieval-substrate split.

`ingest_item()` is the single-item unit both the job-queue path (connector
runs discovering many items) and the synchronous upload endpoint (one item,
no discover phase) share, so there's exactly one place that does
fetch->parse->normalize->quality-gate->persist->index->graph-process.

Orchestrated as a Prefect flow (report's noted Airflow/Prefect/Dagster
upgrade path from "a worker polling loop"): `run_connector_job` is the
parent flow, `ingest_item` runs as a subflow per discovered item -- a real
fan-out shape, not just a label on a linear function -- and the
network/model/DB-touching steps are tasks with automatic retries. Runs
against Prefect's built-in ephemeral local API by default (no server to
stand up); set `PREFECT_API_URL` to point at a real Prefect server/Cloud
for production-grade run history and alerting.
"""

from __future__ import annotations

import asyncio

from prefect import flow, task
from prefect.tasks import exponential_backoff
from sqlalchemy import select

from wardline.common.logging import get_logger
from wardline.connectors.base import Connector, RawObject, SourceItem
from wardline.ingestion.normalize import clean_text, detect_language
from wardline.ingestion.quality_gates import check_document
from wardline.storage.blobstore import get_blob_store
from wardline.storage.catalog import record_run, register_source
from wardline.storage.db import sync_session
from wardline.storage.models.documents import Document

logger = get_logger(__name__)

# Network/model/DB calls get retried with backoff; everything else is a
# task purely for Prefect's run-graph observability, not because it needs
# retrying.
_RETRYABLE = {"retries": 2, "retry_delay_seconds": exponential_backoff(2), "retry_jitter_factor": 0.3}


@task(**_RETRYABLE)
async def _fetch_task(connector: Connector, item: SourceItem) -> RawObject:
    return await connector.fetch(item)


@task
def _find_duplicate_task(connector_name: str, content_hash: str) -> str | None:
    with sync_session() as db:
        existing = (
            db.execute(
                select(Document).where(
                    Document.content_hash == content_hash,
                    Document.source_connector == connector_name,
                )
            )
            .scalars()
            .first()
        )
        return existing.id if existing else None


@task
def _parse_task(connector: Connector, raw: RawObject):
    return connector.parse(raw)


@task(**_RETRYABLE)
def _persist_task(connector: Connector, raw: RawObject, parsed, prov) -> dict:
    """Normalize, quality-gate, write the blob, and insert the Document
    row. Returns {"status", "doc_id", "text"} -- "text" only present when
    the caller still needs to index it (status == "active").
    """
    text = clean_text(parsed.text)
    lang = detect_language(text) if text else "en"
    quality = check_document(text, prov.license)

    blob_store = get_blob_store()
    blob_key = f"{connector.name}/{prov.content_hash}"
    blob_store.put(blob_key, raw.content)
    blob_store.put_json_sidecar(
        blob_key,
        {
            "uri": prov.uri,
            "fetched_at": prov.fetched_at,
            "license": prov.license,
            "content_hash": prov.content_hash,
            "source_connector": prov.source_connector,
        },
    )

    doc = Document(
        uri=parsed.uri,
        title=parsed.title,
        published_at=parsed.published_at,
        fetched_at=prov.fetched_at,
        license=prov.license,
        content_hash=prov.content_hash,
        lang=lang,
        status="active" if quality.passed else "quarantined",
        quarantine_reason=quality.reason,
        source_connector=connector.name,
        blob_key=blob_key,
        extra=parsed.extra,
    )
    with sync_session() as db:
        db.add(doc)
        db.flush()
        doc_id = doc.id

    if not quality.passed:
        logger.info("ingest.quarantined", doc_id=doc_id, reason=quality.reason)
        return {"status": "quarantined", "doc_id": doc_id}
    return {"status": "active", "doc_id": doc_id, "text": text}


@task(**_RETRYABLE)
def _index_and_graph_task(doc_id: str, text: str) -> None:
    with sync_session() as db:
        from wardline.retrieval.index import index_document

        index_document(db, doc_id, text)
    with sync_session() as db:
        from wardline.graph.pipeline import process_document_for_graph

        graph_stats = process_document_for_graph(db, doc_id)
        logger.info("ingest.graph_processed", doc_id=doc_id, **graph_stats)


@flow
async def ingest_item(connector: Connector, item: SourceItem) -> dict:
    """Fetch -> parse -> normalize -> quality-gate -> persist -> index ->
    graph-process a single discovered item. Returns {"status": ..., "doc_id": ...}."""
    try:
        raw = await _fetch_task(connector, item)
    except Exception as exc:
        logger.error("ingest.fetch_failed", connector=connector.name, ref=item.ref, error=str(exc))
        return {"status": "error", "doc_id": None, "error": str(exc)}

    prov = connector.provenance(item, raw)

    existing_id = _find_duplicate_task(connector.name, prov.content_hash)
    if existing_id:
        return {"status": "duplicate", "doc_id": existing_id}

    try:
        parsed = _parse_task(connector, raw)
    except Exception as exc:
        logger.error("ingest.parse_failed", connector=connector.name, ref=item.ref, error=str(exc))
        return {"status": "error", "doc_id": None, "error": str(exc)}

    persisted = _persist_task(connector, raw, parsed, prov)
    if persisted["status"] == "quarantined":
        return {"status": "quarantined", "doc_id": persisted["doc_id"]}

    _index_and_graph_task(persisted["doc_id"], persisted["text"])
    return {"status": "ingested", "doc_id": persisted["doc_id"]}


def ingest_item_sync(connector: Connector, item: SourceItem) -> dict:
    return asyncio.run(ingest_item(connector, item))


def run_connector_job(connector: Connector, params: dict) -> dict:
    return asyncio.run(_run_connector_job_flow(connector, params))


@flow
async def _run_connector_job_flow(connector: Connector, params: dict) -> dict:
    stats = {"discovered": 0, "ingested": 0, "quarantined": 0, "duplicates": 0, "errors": 0}

    with sync_session() as db:
        register_source(db, connector.name, connector.default_license, config_schema={})

    async for item in connector.discover(**params):
        stats["discovered"] += 1
        result = await ingest_item(connector, item)
        status = result["status"]
        if status == "ingested":
            stats["ingested"] += 1
        elif status == "duplicate":
            stats["duplicates"] += 1
        elif status == "quarantined":
            stats["quarantined"] += 1
        else:
            stats["errors"] += 1

    with sync_session() as db:
        record_run(db, connector.name, rows_added=stats["ingested"])

    return stats
