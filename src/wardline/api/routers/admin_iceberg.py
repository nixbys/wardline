"""On-demand trigger for the Iceberg analytical export
(storage/iceberg_export.py) -- the noted upgrade path from "plain
Postgres tables + MinIO for raw bytes only" for time-travel/schema-
evolution-capable analytics over the audit log. Admin-only: this is an
operational/analytics action, not something every authorized user needs.

Also exposes the signed export receipts (commercialization roadmap Phase 2
/ Pillar 3.3) -- each one is independently verifiable
(storage/iceberg_signing.verify_receipt) using only the fields returned
here, without trusting this deployment's *current* signing key.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.api.deps import get_db, require_role
from wardline.storage.models.governance import ROLE_ADMIN, User
from wardline.storage.models.iceberg import IcebergExportReceipt

router = APIRouter(prefix="/v1/admin/iceberg", tags=["admin-iceberg"])
_admin_only = require_role(ROLE_ADMIN)


@router.post("/export-audit-events")
def export_audit_events(_user: User = Depends(_admin_only)) -> dict:
    from wardline.storage.iceberg_export import export_audit_events as run_export

    return run_export()


@router.get("/export-receipts")
def list_export_receipts(
    db: Session = Depends(get_db), _user: User = Depends(_admin_only)
) -> list[dict]:
    stmt = select(IcebergExportReceipt).order_by(IcebergExportReceipt.created_at.desc()).limit(100)
    return [
        {
            "id": r.id,
            "snapshot_id": r.snapshot_id,
            "row_count": r.row_count,
            "time_range_start": r.time_range_start.isoformat(),
            "time_range_end": r.time_range_end.isoformat(),
            "batch_sha256": r.batch_sha256,
            "algorithm": r.algorithm,
            "signature": base64.b64encode(r.signature).decode("ascii"),
            "public_key": base64.b64encode(r.public_key).decode("ascii"),
            "created_at": r.created_at.isoformat(),
        }
        for r in db.execute(stmt).scalars()
    ]
