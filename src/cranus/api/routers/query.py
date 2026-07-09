"""POST /v1/query — the report's 5.6 API contract.

Defined as a sync `def` (not `async def`) on purpose: FastAPI runs sync path
operations in a worker thread automatically, which is what we want here —
the pipeline does CPU-bound embedding/reranking work and blocking sync DB
calls, neither of which belongs on the asyncio event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from cranus.agent.loop import run_agent
from cranus.api.deps import get_current_user_active, get_db
from cranus.common.config import get_settings
from cranus.common.schemas import QueryRequest, QueryResponse
from cranus.governance.rate_limit import limiter
from cranus.query.pipeline import answer
from cranus.storage.models.governance import User

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
@limiter.limit(f"{get_settings().rate_limit_query_per_minute}/minute")
def run_query(
    request: Request,
    body: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_active),
) -> QueryResponse:
    if body.mode == "research":
        result = run_agent(
            db, user=user, question=body.question, filters=body.filters, max_sources=body.max_sources
        )
    else:
        result = answer(
            db,
            user=user,
            question=body.question,
            mode=body.mode,
            filters=body.filters,
            max_sources=body.max_sources,
        )
    return QueryResponse(**result)
