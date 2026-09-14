"""GET /v1/audit — the shared, browsable query log every authorized user can
read (report 4.6: "everyone sees every search").
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from wardline.api.deps import get_current_user, get_db, require_role
from wardline.governance.audit import coverage_gap_summary, get_events
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

router = APIRouter(prefix="/v1", tags=["audit"])
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)


@router.get("/audit")
def list_audit_events(
    user: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    _caller: User = Depends(get_current_user),
) -> list[dict]:
    events = get_events(db, user_id=user, since=since, limit=limit)
    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "event_type": e.event_type,
            "user_id": e.user_id,
            "payload": e.payload,
            "created_at": e.created_at,
        }
        for e in events
    ]


@router.get("/audit/coverage-gaps")
def get_coverage_gaps(
    since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_role),
) -> list[dict]:
    """Ops Console signal (Phase 6, tracked locally): how often each query
    mode ends without enough evidence to answer, mode-level only -- see
    governance/audit.py's own docstring for why. Admin/analyst only, unlike
    the shared GET /v1/audit log every authenticated user can read -- this
    is operational tooling, not part of the shared search-history feature.
    """
    return coverage_gap_summary(db, since=since)
