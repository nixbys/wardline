"""Runtime "add a source" story (report 4.1 / plan's connector registry):
list registered connectors and trigger a job the worker will pick up.
Admin/analyst only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_db, require_role
from wardline.common.config import get_settings
from wardline.common.errors import AccessDeniedError
from wardline.connectors.registry import get_connector, list_connectors
from wardline.governance import pep
from wardline.storage.catalog import register_source
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User
from wardline.storage.models.ingestion import IngestionJob

router = APIRouter(prefix="/v1/admin/connectors", tags=["admin-connectors"])
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)


class RunConnectorRequest(BaseModel):
    params: dict = {}
    engagement_id: str | None = None


@router.get("")
def list_registered_connectors(_user: User = Depends(_operator_role)) -> list[str]:
    return list(list_connectors().keys())


@router.post("/{name}/run")
def run_connector(
    name: str,
    body: RunConnectorRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_role),
) -> dict:
    connector = get_connector(name)  # raises KeyError -> 500 if unregistered; acceptable for v1

    if connector.requires_engagement:
        target = body.params.get("target")
        if not target:
            raise HTTPException(
                status_code=400,
                detail="this connector requires params.target (the specific target being looked up)",
            )
        try:
            pep.enforce_engagement_scope(db, body.engagement_id, target)
        except AccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    register_source(db, name, connector.default_license, config_schema={})
    db.flush()  # must land before the job insert: no relationship() links Source/IngestionJob
    # for SQLAlchemy's unit-of-work to infer insert order from the raw FK alone
    params = dict(body.params)
    if body.engagement_id:
        params["engagement_id"] = body.engagement_id  # carried into the audited job record
    job = IngestionJob(connector_name=name, params=params)
    db.add(job)
    db.flush()

    if get_settings().job_queue_backend == "kafka":
        from wardline.worker.kafka_queue import publish_job

        publish_job(job.id, name, params)
    # else: the row above is enough -- worker/jobs.py's SKIP LOCKED poll picks it up.

    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}")
def get_job_status(
    job_id: str, db: Session = Depends(get_db), _user: User = Depends(_operator_role)
) -> dict:
    job = db.get(IngestionJob, job_id)
    if job is None:
        return {"error": "not found"}
    return {
        "id": job.id,
        "connector_name": job.connector_name,
        "status": job.status,
        "result": job.result,
        "error": job.error,
    }
