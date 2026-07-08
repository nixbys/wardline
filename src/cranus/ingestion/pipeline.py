"""Orchestrates discover -> fetch -> parse -> normalize -> quality-gate ->
persist for one connector job (report 4.1/4.2). Chunking + embedding happen
separately in retrieval/index.py once a document is durably stored — keeping
"acquire and store" and "make retrievable" as distinct steps mirrors the
report's collection-plane vs. retrieval-substrate split.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from cranus.connectors.base import Connector
from cranus.common.logging import get_logger
from cranus.ingestion.normalize import clean_text, detect_language
from cranus.ingestion.quality_gates import check_document
from cranus.storage.blobstore import get_blob_store
from cranus.storage.catalog import record_run, register_source
from cranus.storage.db import sync_session
from cranus.storage.models.documents import Document

logger = get_logger(__name__)


def run_connector_job(connector: Connector, params: dict) -> dict:
    return asyncio.run(_run_connector_job_async(connector, params))


async def _run_connector_job_async(connector: Connector, params: dict) -> dict:
    blob_store = get_blob_store()
    stats = {"discovered": 0, "ingested": 0, "quarantined": 0, "duplicates": 0, "errors": 0}

    with sync_session() as db:
        register_source(db, connector.name, connector.default_license, config_schema={})

    async for item in connector.discover(**params):
        stats["discovered"] += 1
        try:
            raw = await connector.fetch(item)
        except Exception as exc:  # noqa: BLE001 - one bad item must not kill the whole job
            logger.error("ingest.fetch_failed", connector=connector.name, ref=item.ref, error=str(exc))
            stats["errors"] += 1
            continue

        prov = connector.provenance(item, raw)

        with sync_session() as db:
            existing = db.execute(
                select(Document).where(
                    Document.content_hash == prov.content_hash,
                    Document.source_connector == connector.name,
                )
            ).scalars().first()
            if existing:
                stats["duplicates"] += 1
                continue

        try:
            parsed = connector.parse(raw)
        except Exception as exc:  # noqa: BLE001
            logger.error("ingest.parse_failed", connector=connector.name, ref=item.ref, error=str(exc))
            stats["errors"] += 1
            continue

        text = clean_text(parsed.text)
        lang = detect_language(text) if text else "en"
        quality = check_document(text, prov.license)

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

        if quality.passed:
            stats["ingested"] += 1
            with sync_session() as db:
                from cranus.retrieval.index import index_document

                index_document(db, doc_id, text)
        else:
            stats["quarantined"] += 1
            logger.info("ingest.quarantined", doc_id=doc_id, reason=quality.reason)

    with sync_session() as db:
        record_run(db, connector.name, rows_added=stats["ingested"])

    return stats
