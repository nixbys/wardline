"""Create/list/revoke engagements (governance/engagements.py). Creating one is
admin-only — it's the act of asserting "this specific target lookup is
authorized", which is a bigger claim than the run-of-the-mill ingest/review
actions analysts already do. Analysts can list/read engagements so they know
what scope they're allowed to operate a dual-use connector under.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from wardline.api.deps import get_db, require_role
from wardline.governance.engagements import is_active, revoke_engagement
from wardline.storage.models.engagements import Engagement
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

router = APIRouter(prefix="/v1/admin/engagements", tags=["admin-engagements"])
_admin_only = require_role(ROLE_ADMIN)
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)


class CreateEngagementRequest(BaseModel):
    target: str
    scope_note: str
    evidence_ref: str
    valid_from: datetime
    valid_until: datetime


def _serialize(engagement: Engagement) -> dict:
    return {
        "id": engagement.id,
        "target": engagement.target,
        "scope_note": engagement.scope_note,
        "evidence_ref": engagement.evidence_ref,
        "authorized_by_user_id": engagement.authorized_by_user_id,
        "valid_from": engagement.valid_from.isoformat(),
        "valid_until": engagement.valid_until.isoformat(),
        "revoked_at": engagement.revoked_at.isoformat() if engagement.revoked_at else None,
        "active": is_active(engagement),
    }


@router.post("")
def create_engagement(
    body: CreateEngagementRequest, db=Depends(get_db), admin: User = Depends(_admin_only)
) -> dict:
    if body.valid_until <= body.valid_from:
        raise HTTPException(status_code=400, detail="valid_until must be after valid_from")
    engagement = Engagement(
        target=body.target,
        scope_note=body.scope_note,
        evidence_ref=body.evidence_ref,
        authorized_by_user_id=admin.id,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    )
    db.add(engagement)
    db.flush()
    return _serialize(engagement)


@router.get("")
def list_engagements(db=Depends(get_db), _user: User = Depends(_operator_role)) -> list[dict]:
    rows = list(db.execute(select(Engagement)).scalars())
    return [_serialize(e) for e in rows]


@router.post("/{engagement_id}/revoke")
def revoke(
    engagement_id: str, db=Depends(get_db), _admin: User = Depends(_admin_only)
) -> dict:
    engagement = revoke_engagement(db, engagement_id)
    if engagement is None:
        raise HTTPException(status_code=404, detail="no such engagement")
    return _serialize(engagement)
