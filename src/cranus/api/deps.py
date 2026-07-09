"""Shared FastAPI dependencies: DB session, and the authentication dependency
that doubles as the report's "policy enforcement point" chokepoint — every
authenticated route depends on `get_current_user`, so revocation checks
can't be bypassed by calling a different endpoint.

`get_current_user_active` additionally enforces the kill switch and is used
only on the query/agent surface (see governance/pep.py for why admin routes
must NOT be gated on the kill switch too — it would be a one-way ratchet).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from cranus.common.errors import AccessDeniedError, KillSwitchEngagedError
from cranus.common.security import lookup_key_for_index, verify_api_key
from cranus.governance import pep, rbac
from cranus.storage.db import sync_session
from cranus.storage.models.base import utcnow
from cranus.storage.models.governance import ApiKey, User


def get_db() -> Iterator[Session]:
    with sync_session() as db:
        yield db


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer ") :]

    api_key = (
        db.query(ApiKey)
        .filter(ApiKey.lookup_hash == lookup_key_for_index(token), ApiKey.revoked.is_(False))
        .first()
    )
    if api_key is None or not verify_api_key(token, api_key.key_hash):
        raise HTTPException(status_code=401, detail="invalid or revoked API key")

    user = db.get(User, api_key.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")

    try:
        pep.enforce_authenticated(user)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    api_key.last_used_at = utcnow()
    db.flush()
    return user


def get_current_user_active(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    try:
        pep.enforce_kill_switch(db)
    except KillSwitchEngagedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return user


def require_role(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        try:
            rbac.require_role(user, *roles)
        except AccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return user

    return dependency
