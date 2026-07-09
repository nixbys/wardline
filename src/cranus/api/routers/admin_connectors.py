"""Runtime "add a source" story (report 4.1 / plan's connector registry):
list registered connectors and trigger a job the worker will pick up.
Admin/analyst only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cranus.api.deps import get_db, require_role
from cranus.connectors.registry import get_connector, list_connectors
from cranus.storage.catalog import register_source
from cranus.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User
from cranus.storage.models.ingestion import IngestionJob

router = APIRouter(prefix="/v1/admin/connectors", tags=["admin-connectors"])
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)


class RunConnectorRequest(BaseModel):
    params: dict = {}


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
    register_source(db, name, connector.default_license, config_schema={})
    db.flush()  # must land before the job insert: no relationship() links Source/IngestionJob
    # for SQLAlchemy's unit-of-work to infer insert order from the raw FK alone
    job = IngestionJob(connector_name=name, params=body.params)
    db.add(job)
    db.flush()
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
