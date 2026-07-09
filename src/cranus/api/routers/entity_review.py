"""Human-in-the-loop entity resolution review queue (report 4.5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cranus.api.deps import get_current_user_id, get_db
from cranus.graph.entity_resolution import review
from cranus.storage.models.entities import Entity

router = APIRouter(prefix="/v1/admin/entity-review", tags=["entity-review"])


class ReviewDecision(BaseModel):
    decision: str  # "merged" | "rejected"


@router.get("/queue")
def list_queue(db: Session = Depends(get_db)) -> list[dict]:
    pending = review.list_pending(db)
    out = []
    for r in pending:
        entity_a = db.get(Entity, r.entity_a_id) if r.entity_a_id else None
        entity_b = db.get(Entity, r.entity_b_id) if r.entity_b_id else None
        out.append(
            {
                "id": r.id,
                "score": r.score,
                "entity_a": {"id": entity_a.id, "name": entity_a.canonical_name} if entity_a else None,
                "entity_b": {"id": entity_b.id, "name": entity_b.canonical_name} if entity_b else None,
                "created_at": r.created_at,
            }
        )
    return out


@router.post("/{review_id}/decision")
def decide(
    review_id: str,
    body: ReviewDecision,
    db: Session = Depends(get_db),
    user_id: str | None = Depends(get_current_user_id),
) -> dict:
    result = review.decide(db, review_id, body.decision, user_id)
    return {"id": result.id, "status": result.status}
