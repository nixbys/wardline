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
from wardline.api.deps import get_current_user_active, get_db
from wardline.common.config import get_settings
from wardline.common.errors import AccessDeniedError
from wardline.common.schemas import QueryRequest, QueryResponse
from wardline.governance import billing, entitlements
from wardline.governance.rate_limit import limiter
from wardline.query.pipeline import answer
from wardline.storage.models.governance import User

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
@limiter.limit(f"{get_settings().rate_limit_query_per_minute}/minute")
def run_query(
    request: Request,
    body: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_active),
) -> QueryResponse:
    plan_id = billing.current_plan_id(db, user)
    try:
        entitlements.enforce_mode_allowed(plan_id, body.mode)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    max_sources = entitlements.capped_max_sources(plan_id, body.max_sources)

    if body.mode == "research":
        result = run_agent(
            db, user=user, question=body.question, filters=body.filters, max_sources=max_sources
        )
    else:
        result = answer(
            db,
            user=user,
            question=body.question,
            mode=body.mode,
            filters=body.filters,
            max_sources=max_sources,
        )
    return QueryResponse(**result)
