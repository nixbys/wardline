"""Real Iceberg tables over the existing object store -- the noted upgrade
path from "plain Postgres tables + MinIO for raw bytes only" for analytics
needing time-travel/schema evolution (see the README's scope-reductions
table). No new infrastructure: the catalog reuses this app's own Postgres
(pyiceberg's `SqlCatalog` against any SQLAlchemy URL), and the warehouse
reuses whichever `blob_backend` is already configured -- the local
filesystem by default, the same MinIO/S3 bucket the bronze tier already
uses when `BLOB_BACKEND=s3`.

Mirrors `audit_events` -- this app's own append-only, immutable table
("nothing about this row is ever mutated after insert", per its own
docstring), exactly the kind of data time-travel queries are for ("what
did the audit trail look like as of last Tuesday", "what did this
document's status history look like before a schema change added a
field"). Postgres stays the system of record; this is a read-optimized,
time-travel-capable analytical copy, refreshed on demand or on a
schedule, not a replacement.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from wardline.common.config import get_settings
from wardline.common.logging import get_logger
from wardline.storage import iceberg_signing
from wardline.storage.db import sync_session
from wardline.storage.models.governance import AuditEvent
from wardline.storage.models.iceberg import IcebergExportReceipt

logger = get_logger(__name__)

NAMESPACE = "wardline"
TABLE_NAME = "audit_events"
_FULL_TABLE = f"{NAMESPACE}.{TABLE_NAME}"


def _warehouse_location() -> str:
    settings = get_settings()
    if settings.blob_backend == "s3":
        return f"s3://{settings.s3_bucket}/iceberg-warehouse"
    root = Path(settings.blob_local_root).resolve().parent / "iceberg-warehouse"
    root.mkdir(parents=True, exist_ok=True)
    return f"file://{root}"


@lru_cache
def _catalog():
    from pyiceberg.catalog.sql import SqlCatalog

    settings = get_settings()
    properties = {"uri": settings.database_url, "warehouse": _warehouse_location()}
    if settings.blob_backend == "s3":
        properties.update(
            {
                "s3.endpoint": settings.s3_endpoint_url,
                "s3.access-key-id": settings.s3_access_key,
                "s3.secret-access-key": settings.s3_secret_key,
                "s3.region": settings.s3_region,
            }
        )
    catalog = SqlCatalog("wardline", **properties)
    catalog.create_namespace_if_not_exists(NAMESPACE)
    return catalog


def _last_exported_at(table):
    import pyarrow.compute as pc

    arrow_tbl = table.scan(selected_fields=("created_at",)).to_arrow()
    if arrow_tbl.num_rows == 0:
        return None
    return pc.max(arrow_tbl["created_at"]).as_py()


def export_audit_events() -> dict:
    """Appends every `audit_events` row not already present into the real
    Iceberg table (idempotent: tracks the latest `created_at` already
    exported via a scan of the Iceberg table itself, rather than a
    separate bookmark that could drift out of sync with it).
    """
    import pyarrow as pa

    catalog = _catalog()
    table = catalog.create_table_if_not_exists(
        _FULL_TABLE,
        schema=pa.schema(
            [
                ("id", pa.string()),
                ("session_id", pa.string()),
                ("event_type", pa.string()),
                ("user_id", pa.string()),
                ("payload", pa.string()),  # JSON-encoded; Iceberg has no native JSON type
                ("created_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
    )
    since = _last_exported_at(table)

    session = sync_session()
    with session as db:
        query = db.query(AuditEvent).order_by(AuditEvent.created_at)
        if since is not None:
            query = query.filter(AuditEvent.created_at > since)
        rows = list(query)

    if not rows:
        logger.info("iceberg_export.no_new_rows")
        return {"exported": 0}

    batch = pa.table(
        {
            "id": [r.id for r in rows],
            "session_id": [r.session_id for r in rows],
            "event_type": [r.event_type for r in rows],
            "user_id": [r.user_id for r in rows],
            "payload": [json.dumps(r.payload) for r in rows],
            "created_at": [r.created_at for r in rows],
        },
        schema=table.schema().as_arrow(),
    )
    table.append(batch)
    logger.info("iceberg_export.appended", rows=len(rows))

    snapshot = table.current_snapshot()
    _record_receipt(rows, snapshot.snapshot_id if snapshot else "unknown")

    return {"exported": len(rows)}


def _record_receipt(rows: list[AuditEvent], snapshot_id: str) -> None:
    """Best-effort: signing is opt-in (settings.iceberg_export_signing_enabled)
    and needs a keypair generated first, so this is a no-op — not an
    error — until both are set up. See storage/iceberg_signing.py."""
    receipt = iceberg_signing.build_receipt(rows, snapshot_id)
    signed = iceberg_signing.sign_receipt(receipt)
    if signed is None:
        return
    signature, public_key = signed
    with sync_session() as db:
        db.add(
            IcebergExportReceipt(
                snapshot_id=receipt["snapshot_id"],
                row_count=receipt["row_count"],
                time_range_start=receipt["time_range_start"],
                time_range_end=receipt["time_range_end"],
                batch_sha256=receipt["batch_sha256"],
                algorithm=iceberg_signing.ALGORITHM,
                signature=signature,
                public_key=public_key,
            )
        )
    logger.info("iceberg_export.receipt_signed", snapshot_id=receipt["snapshot_id"])
