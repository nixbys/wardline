"""User/API-key management and the admin kill switch (report 4.6). Admin only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.api.deps import get_db, require_role
from wardline.common.security import generate_api_key, lookup_key_for_index
from wardline.governance import accounts, kill_switch
from wardline.storage.models.governance import ROLE_ADMIN, ROLES, ApiKey, User

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_admin_only = require_role(ROLE_ADMIN)


class CreateUserRequest(BaseModel):
    email: str
    role: str = "viewer"


class InviteUserRequest(BaseModel):
    email: str
    role: str = "viewer"


class KillSwitchRequest(BaseModel):
    enabled: bool


@router.post("/users")
def create_user(
    body: CreateUserRequest, db: Session = Depends(get_db), _admin: User = Depends(_admin_only)
) -> dict:
    if body.role not in ROLES:
        return {"error": f"role must be one of {ROLES}"}
    user = db.query(User).filter(User.email == body.email).first()
    if user is None:
        user = User(email=body.email, role=body.role)
        db.add(user)
        db.flush()
    plaintext, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=user.id, key_hash=key_hash, lookup_hash=lookup_key_for_index(plaintext), scopes=["*"]
    )
    db.add(api_key)
    db.flush()
    return {"user_id": user.id, "email": user.email, "role": user.role, "api_key": plaintext}


@router.post("/users/invite")
def invite_user(
    body: InviteUserRequest, db: Session = Depends(get_db), _admin: User = Depends(_admin_only)
) -> dict:
    """Self-serve counterpart to `create_user` above: instead of minting a
    usable API key immediately (which only makes sense when the admin and
    the new user are the same person doing initial setup), this emails an
    invite link the recipient uses to set their own password
    (`POST /v1/auth/accept-invite`) — the right shape for adding a real
    teammate who should choose and hold their own credential.
    """
    if body.role not in ROLES:
        return {"error": f"role must be one of {ROLES}"}
    accounts.create_invite(db, email=body.email, role=body.role)
    return {"message": f"invite sent to {body.email}"}


@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(_admin_only)) -> list[dict]:
    users = list(db.execute(select(User)).scalars())
    return [{"id": u.id, "email": u.email, "role": u.role, "revoked": u.revoked} for u in users]


@router.post("/users/{user_id}/revoke")
def revoke_user(
    user_id: str, db: Session = Depends(get_db), _admin: User = Depends(_admin_only)
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        return {"error": "not found"}
    user.revoked = True
    for key in db.query(ApiKey).filter(ApiKey.user_id == user_id):
        key.revoked = True
    db.flush()
    return {"id": user.id, "revoked": user.revoked}


@router.post("/kill-switch")
def set_kill_switch(
    body: KillSwitchRequest, db: Session = Depends(get_db), _admin: User = Depends(_admin_only)
) -> dict:
    kill_switch.set_enabled(db, body.enabled)
    return {"enabled": body.enabled}


@router.get("/kill-switch")
def get_kill_switch(db: Session = Depends(get_db), _admin: User = Depends(_admin_only)) -> dict:
    return {"enabled": kill_switch.is_enabled(db)}
