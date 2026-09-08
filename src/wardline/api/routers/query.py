"""POST /v1/query — the report's 5.6 API contract.

Defined as a sync `def` (not `async def`) on purpose: FastAPI runs sync path
operations in a worker thread automatically, which is what we want here —
the pipeline does CPU-bound embedding/reranking work and blocking sync DB
calls, neither of which belongs on the asyncio event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from wardline.agent.loop import run_agent
from wardline.api.deps import get_current_user_active, get_db, get_vault_dek
from wardline.common.config import get_settings
from wardline.common.errors import AccessDeniedError
from wardline.common.plans import get_plan
from wardline.common.schemas import QueryRequest, QueryResponse
from wardline.common.security import lookup_key_for_index, verify_api_key
from wardline.governance import billing, entitlements
from wardline.governance.rate_limit import limiter
from wardline.query.pipeline import answer
from wardline.security.vault import should_encrypt_history
from wardline.storage.db import sync_session
from wardline.storage.models.governance import ApiKey, User

router = APIRouter(prefix="/v1", tags=["query"])


def _resolve_plan_rate_limit(db: Session, key: str) -> str | None:
    """The plan-specific limit string for `key`'s owning user, or None if
    it can't be resolved (caller falls back to the flat default). Split
    out from `_plan_aware_query_limit` below purely so it's unit-testable
    against an injected Session, without needing a real
    `sync_session()`/Postgres connection.
    """
    api_key = (
        db.query(ApiKey)
        .filter(ApiKey.lookup_hash == lookup_key_for_index(key), ApiKey.revoked.is_(False))
        .first()
    )
    if api_key is None or not verify_api_key(key, api_key.key_hash):
        return None
    user = db.get(User, api_key.user_id)
    if user is None:
        return None
    plan_id = billing.current_plan_id(db, user)
    return f"{get_plan(plan_id).query_rate_limit_per_minute}/minute"


def _plan_aware_query_limit(key: str) -> str:
    """Per-plan ceiling for this route (commercialization roadmap Pillar 5)
    -- a flat global limit doesn't reflect the entitlement model; a
    Free-tier key and an Enterprise key shouldn't share one ceiling. `key`
    is whatever `governance.rate_limit._key_func` returned for this
    request: the raw bearer token for an authenticated caller, or their
    remote address otherwise (this route always requires auth via
    `get_current_user_active`, so in practice it's always a token).

    Scoped to `AUTH_MODE=api_key` only. Resolving a caller's plan under
    `AUTH_MODE=oidc` would mean re-validating the JWT here and, for a
    never-seen-before caller, creating their `User` row before the real
    `get_current_user_active` dependency does the same -- extra work and a
    double-creation risk in a path that must never itself fail a request.
    OIDC callers get the flat default limit for now; revisit if per-plan
    limits become load-bearing for an OIDC deployment.
    """
    settings = get_settings()
    default = f"{settings.rate_limit_query_per_minute}/minute"
    if settings.auth_mode != "api_key" or not key:
        return default
    try:
        with sync_session() as db:
            resolved = _resolve_plan_rate_limit(db, key)
    except Exception:
        # Rate-limit resolution must never be the reason a request 500s --
        # fail open to the conservative flat default, not to "unlimited".
        return default
    return resolved or default


@router.post("/query", response_model=QueryResponse)
@limiter.limit(_plan_aware_query_limit)
def run_query(
    request: Request,
    body: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_active),
    dek: bytes | None = Depends(get_vault_dek),
) -> QueryResponse:
    plan_id = billing.current_plan_id(db, user)
    try:
        entitlements.enforce_mode_allowed(plan_id, body.mode)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    max_sources = entitlements.capped_max_sources(plan_id, body.max_sources)

    # Only a Pro solo user's own question gets encrypted (commercialization
    # roadmap Phase 2) -- should_encrypt_history is the single source of
    # truth for that gate; dek itself is already None for anyone without a
    # live session bridge (OIDC, no vault, etc.), but a Team/Free user with
    # a bridged session must still not have their question encrypted just
    # because a DEK happens to be resolvable.
    query_dek = dek if should_encrypt_history(db, user) else None

    if body.mode == "research":
        result = run_agent(
            db,
            user=user,
            question=body.question,
            filters=body.filters,
            max_sources=max_sources,
            dek=query_dek,
        )
    else:
        result = answer(
            db,
            user=user,
            question=body.question,
            mode=body.mode,
            filters=body.filters,
            max_sources=max_sources,
            dek=query_dek,
        )
    return QueryResponse(**result)
