"""GET /v1/session/{id} — folds the append-only audit_events for one session
into the report's QuerySession shape (this *is* the "public search history").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cranus.api.deps import get_db
from cranus.common.schemas import QuerySession
from cranus.governance.audit import get_session_events

router = APIRouter(prefix="/v1", tags=["session"])


@router.get("/session/{session_id}", response_model=QuerySession)
def get_session(session_id: str, db: Session = Depends(get_db)) -> QuerySession:
    events = get_session_events(db, session_id)
    if not events:
        raise HTTPException(status_code=404, detail="session not found")

    opened = next((e for e in events if e.event_type == "query_opened"), None)
    closed = next((e for e in events if e.event_type == "query_closed"), None)

    return QuerySession(
        session_id=session_id,
        user_id=(opened.user_id if opened else None) or "anonymous",
        question=(opened.payload.get("question") if opened else "") or "",
        asked_at=opened.created_at if opened else events[0].created_at,
        retrieved=(closed.payload.get("retrieved") if closed else []) or [],
        answer_hash=(closed.payload.get("answer_hash") if closed else None),
        latency_ms=(closed.payload.get("latency_ms") if closed else None),
        token_cost=(closed.payload.get("token_cost") if closed else None),
    )
