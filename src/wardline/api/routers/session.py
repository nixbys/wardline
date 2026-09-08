"""GET /v1/session/{id} — folds the append-only audit_events for one session
into the report's QuerySession shape (this *is* the "public search history").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from wardline.api.deps import get_current_user, get_db, get_vault_dek
from wardline.common.errors import AccessDeniedError
from wardline.common.schemas import QuerySession
from wardline.governance.audit import build_query_session, get_session_events
from wardline.storage.models.governance import User

router = APIRouter(prefix="/v1", tags=["session"])


@router.get("/session/{session_id}", response_model=QuerySession)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    dek: bytes | None = Depends(get_vault_dek),
) -> QuerySession:
    events = get_session_events(db, session_id)
    try:
        return build_query_session(events, user, dek)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
