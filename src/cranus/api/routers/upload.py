"""POST /v1/documents/upload — bring-your-own-corpus (report's connector
plugin story): hands the file straight to the `upload` connector, bypassing
discover(). Analyst/admin only, matching the other ingestion-triggering
endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from cranus.api.deps import get_db, require_role
from cranus.connectors.base import SourceItem
from cranus.connectors.registry import get_connector
from cranus.ingestion.pipeline import ingest_item
from cranus.storage.catalog import register_source
from cranus.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

router = APIRouter(prefix="/v1/documents", tags=["upload"])
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    license: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_role),
) -> dict:
    connector = get_connector("upload")
    register_source(db, "upload", connector.default_license, config_schema={})
    db.commit()

    content = await file.read()
    item = SourceItem(
        ref=file.filename or "upload",
        extra={"content": content, "filename": file.filename, "content_type": file.content_type, "license": license},
    )
    result = await ingest_item(connector, item)
    return result
