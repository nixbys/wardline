"""POST /v1/query — the report's 5.6 API contract.

Defined as a sync `def` (not `async def`) on purpose: FastAPI runs sync path
operations in a worker thread automatically, which is what we want here —
the pipeline does CPU-bound embedding/reranking work and blocking sync DB
calls, neither of which belongs on the asyncio event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cranus.api.deps import get_current_user_id, get_db
from cranus.common.schemas import QueryRequest, QueryResponse
from cranus.query.pipeline import answer

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
def run_query(
    request: QueryRequest,
    db: Session = Depends(get_db),
    user_id: str | None = Depends(get_current_user_id),
) -> QueryResponse:
    result = answer(
        db,
        user_id=user_id,
        question=request.question,
        mode=request.mode,
        filters=request.filters,
        max_sources=request.max_sources,
    )
    return QueryResponse(**result)
