"""On-demand trigger for the Iceberg analytical export
(storage/iceberg_export.py) -- the noted upgrade path from "plain
Postgres tables + MinIO for raw bytes only" for time-travel/schema-
evolution-capable analytics over the audit log. Admin-only: this is an
operational/analytics action, not something every authorized user needs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from wardline.api.deps import require_role
from wardline.storage.models.governance import ROLE_ADMIN, User

router = APIRouter(prefix="/v1/admin/iceberg", tags=["admin-iceberg"])
_admin_only = require_role(ROLE_ADMIN)


@router.post("/export-audit-events")
def export_audit_events(_user: User = Depends(_admin_only)) -> dict:
    from wardline.storage.iceberg_export import export_audit_events as run_export

    return run_export()
