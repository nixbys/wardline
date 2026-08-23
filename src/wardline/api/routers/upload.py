"""POST /v1/documents/upload — bring-your-own-corpus (report's connector
plugin story): hands the file straight to the `upload` connector, bypassing
discover(). Analyst/admin only, matching the other ingestion-triggering
endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from wardline.api.deps import get_db, require_role
from wardline.common.config import get_settings
from wardline.connectors.base import SourceItem
from wardline.connectors.registry import get_connector
from wardline.ingestion.pipeline import ingest_item
from wardline.storage.catalog import register_source
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

router = APIRouter(prefix="/v1/documents", tags=["upload"])
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)

_READ_CHUNK_BYTES = 1024 * 1024


async def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read in chunks and abort once over budget, instead of `file.read()`
    unconditionally buffering an arbitrarily large body into memory first —
    the check has to happen during the read, not after it, or the DoS it's
    meant to prevent has already happened by the time we'd reject it.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"file exceeds the {max_bytes} byte upload limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


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

    content = await _read_bounded(file, get_settings().upload_max_bytes)
    item = SourceItem(
        ref=file.filename or "upload",
        extra={"content": content, "filename": file.filename, "content_type": file.content_type, "license": license},
    )
    result = await ingest_item(connector, item)
    return result
