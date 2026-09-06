"""Org/workspace endpoints (commercialization roadmap Pillar 1). Thin
wrapper around `governance/orgs.py`, matching this codebase's existing
router/business-logic split.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_current_user, get_db
from wardline.common.errors import AccessDeniedError
from wardline.governance import orgs
from wardline.storage.models.governance import User

router = APIRouter(prefix="/v1/orgs", tags=["orgs"])


class CreateOrganizationRequest(BaseModel):
    name: str


class InviteToOrgRequest(BaseModel):
    email: str
    role: str = "viewer"


def _require_org(user: User) -> str:
    if user.org_id is None:
        raise HTTPException(status_code=404, detail="you don't belong to an organization")
    return user.org_id


@router.post("")
def create_organization(
    body: CreateOrganizationRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    try:
        org = orgs.create_organization(db, owner=user, name=body.name)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": org.id, "name": org.name, "owner_user_id": org.owner_user_id}


@router.get("/me")
def my_organization(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict | None:
    if user.org_id is None:
        return None
    org = orgs.get_organization(db, user.org_id)
    if org is None:
        return None
    return {"id": org.id, "name": org.name, "owner_user_id": org.owner_user_id}


@router.post("/invite")
def invite_to_org(
    body: InviteToOrgRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    org_id = _require_org(user)
    org = orgs.get_organization(db, org_id)
    try:
        orgs.invite_to_org(db, org=org, inviter=user, email=body.email, role=body.role)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"message": f"invite sent to {body.email}"}


@router.get("/members")
def list_members(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    org_id = _require_org(user)
    org = orgs.get_organization(db, org_id)
    if user.id != org.owner_user_id:
        raise HTTPException(status_code=403, detail="only the organization's owner can list members")
    return [{"id": m.id, "email": m.email, "role": m.role} for m in orgs.list_org_members(db, org)]
