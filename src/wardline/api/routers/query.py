"""POST /v1/query — the report's 5.6 API contract.

Defined as a sync `def` (not `async def`) on purpose: FastAPI runs sync path
operations in a worker thread automatically, which is what we want here —
the pipeline does CPU-bound embedding/reranking work and blocking sync DB
calls, neither of which belongs on the asyncio event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from wardline.agent.loop import run_agent
from wardline.api.deps import get_current_user_active, get_db, get_vault_dek
from wardline.common.config import get_settings
from wardline.common.schemas import QueryRequest, QueryResponse
from wardline.governance.rate_limit import limiter
from wardline.query.pipeline import answer
from wardline.security.vault import should_encrypt_history
from wardline.storage.models.governance import User

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
@limiter.limit(f"{get_settings().rate_limit_query_per_minute}/minute")
def run_query(
    request: Request,
    body: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_active),
    dek: bytes | None = Depends(get_vault_dek),
) -> QueryResponse:
    max_sources = min(body.max_sources, get_settings().query_max_sources)

    # dek is None for anyone without a live session bridge (OIDC, no vault);
    # should_encrypt_history also keeps an org member's question readable to
    # the org even when a key happens to be resolvable.
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
